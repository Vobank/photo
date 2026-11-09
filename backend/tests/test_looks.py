"""Styles, prompt enhancement, variations, detail pass and reference images."""

from __future__ import annotations

import io
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photo.api.app import Services
from photo.auto import MEDIUM_STYLE, STYLE_MEDIUM
from photo.catalog import default_catalog
from photo.engine.pipelines import BuildInputs, build, build_enhance, detail_size
from photo.schemas import MAX_PIXELS, GenerateParams
from photo.styles import STYLES, apply_style, get_style

from .conftest import install_fake_model

SOME_ID = "01m6zd09e8p1ha162sxd24cqtq"


def _graph(model: str, variant: str, inputs: BuildInputs | None = None, **kw: Any) -> dict:
    spec = default_catalog().get(model)
    p = GenerateParams.model_validate({"model": model, "prompt": "a red fox", **kw})
    built = build(p, spec, spec.variant_files(spec.variant(variant)), 7, "x", inputs)
    return built.graph.to_api()


def _types(api: dict) -> list[str]:
    return [n["class_type"] for n in api.values()]


def _one(api: dict, class_type: str) -> dict:
    (node,) = [n for n in api.values() if n["class_type"] == class_type]
    return node["inputs"]


# ---- styles and enhancement ---------------------------------------------------------


def test_style_suffix_applied_without_enhancement() -> None:
    api = _graph("z-image-turbo", "nvfp4", style="noir")
    assert _one(api, "CLIPTextEncode")["text"].startswith("a red fox. moody low-key lighting")
    assert "TextGenerateV2" not in _types(api)


def test_enhancement_wires_language_model_into_encoder() -> None:
    api = _graph("z-image-turbo", "nvfp4", style="film", enhance=True)
    gen_id = next(k for k, n in api.items() if n["class_type"] == "TextGenerateV2")
    gen = api[gen_id]["inputs"]
    assert "Idea: a red fox" in gen["prompt"] and "Portra" in gen["prompt"]
    assert gen["sampling_mode.seed"] == 7
    assert _one(api, "CLIPTextEncode")["text"] == [gen_id, 0]
    assert _one(api, "PreviewAny")["source"] == [gen_id, 0]


def test_every_style_is_well_formed() -> None:
    ids = [s.id for s in STYLES]
    assert len(ids) == len(set(ids))
    # Automatic mode can route every style, and every medium has a recipe.
    assert set(ids) == set(STYLE_MEDIUM)
    assert all(get_style(style) for style in MEDIUM_STYLE.values())
    for s in STYLES:
        assert s.suffix and s.direction and not s.suffix.endswith(".")
    assert get_style("nope") is None
    assert apply_style("x", None) == "x"


def test_enhance_only_graph() -> None:
    built = build_enhance("qwen.safetensors", "кот", get_style("anime"), 5, has_refs=False)
    api = built.graph.to_api()
    assert _types(api) == ["CLIPLoader", "TextGenerateV2", "PreviewAny"]
    assert built.output_node == built.prompt_node


# ---- variation and detail ------------------------------------------------------------


def test_variation_starts_from_the_source_picture() -> None:
    api = _graph(
        "z-image-turbo",
        "nvfp4",
        BuildInputs(variation_source="photo-src.png"),
        variation_of=SOME_ID,
        variation_strength=0.4,
        batch_size=2,
    )
    assert _one(api, "LoadImage")["image"] == "photo-src.png"
    assert _one(api, "ImageScale")["crop"] == "center"
    assert _one(api, "RepeatLatentBatch")["amount"] == 2
    assert _one(api, "KSampler")["denoise"] == 0.4
    assert "EmptySD3LatentImage" not in _types(api)


def test_detail_pass_upscales_and_refines() -> None:
    api = _graph("z-image-turbo", "nvfp4", detail=True)
    up = _one(api, "LatentUpscale")
    assert (up["width"], up["height"]) == (1536, 1536)
    denoises = sorted(n["inputs"]["denoise"] for n in api.values() if n["class_type"] == "KSampler")
    assert denoises == [0.38, 1.0]


@pytest.mark.parametrize(("w", "h"), [(1024, 1024), (2048, 2048), (1344, 768), (2048, 1152)])
def test_detail_size_respects_budget(w: int, h: int) -> None:
    dw, dh = detail_size(w, h)
    assert dw % 16 == 0
    assert dh % 16 == 0
    assert dw * dh <= MAX_PIXELS * 1.02
    assert dw >= w
    assert dh >= h


def test_references_and_variation_are_exclusive() -> None:
    with pytest.raises(ValueError, match="either"):
        GenerateParams(model="m", prompt="x", references=[SOME_ID], variation_of=SOME_ID)


# ---- FLUX.2 Klein references ---------------------------------------------------------


def test_klein_references_condition_both_branches() -> None:
    api = _graph("flux2-klein-4b", "nvfp4", BuildInputs(references=("a.png", "b.png")))
    assert _types(api).count("LoadImage") == 2
    assert _types(api).count("ReferenceLatent") == 4
    assert _one(api, "CLIPLoader")["type"] == "flux2"
    assert _one(api, "Flux2Scheduler")["steps"] == 4
    guider = _one(api, "CFGGuider")
    assert api[guider["positive"][0]]["class_type"] == "ReferenceLatent"
    assert api[guider["negative"][0]]["class_type"] == "ReferenceLatent"


def test_klein_enhancement_uses_separate_writer() -> None:
    api = _graph("flux2-klein-4b", "fp8", BuildInputs(references=("a.png",)), enhance=True)
    types = sorted(n["inputs"]["type"] for n in api.values() if n["class_type"] == "CLIPLoader")
    assert types == ["flux2", "lumina2"]
    assert "reference image" in _one(api, "TextGenerateV2")["prompt"]


# ---- API -----------------------------------------------------------------------------


def _png(w: int = 40, h: int = 30, mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    color = (10, 200, 30, 0) if mode == "RGBA" else (10, 200, 30)
    Image.new(mode, (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _upload(client: TestClient, data: bytes, name: str = "x.png") -> Any:
    return client.post("/api/v1/uploads", files={"file": (name, data, "image/png")})


def _wait(client: TestClient, job_id: str) -> dict:
    job: dict = {}
    for _ in range(250):
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(job)


def _job(client: TestClient, **body: Any) -> Any:
    return client.post("/api/v1/jobs", json={"model": "z-image-turbo", "prompt": "x", **body})


def test_upload_normalises_and_dedupes(client: TestClient) -> None:
    first = _upload(client, _png(mode="RGBA"))
    assert first.status_code == 201
    body = first.json()
    assert (body["width"], body["height"]) == (40, 30)
    assert _upload(client, _png(mode="RGBA")).json()["id"] == body["id"]
    stored = client.get(f"/api/v1/uploads/{body['id']}/file").content
    with Image.open(io.BytesIO(stored)) as img:
        assert img.mode == "RGB"
        assert img.getpixel((0, 0)) == (255, 255, 255)  # transparency flattened onto white
    assert client.get(f"/api/v1/uploads/{body['id']}/thumb").status_code == 200


def test_upload_applies_exif_rotation_and_drops_metadata(client: TestClient) -> None:
    img = Image.new("RGB", (60, 20), (1, 2, 3))
    exif = img.getexif()
    exif[0x0112] = 6  # display rotated by 90 degrees
    exif[0x010F] = "SecretCam"  # camera maker must not survive
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    body = _upload(client, buf.getvalue(), "p.jpg").json()
    assert (body["width"], body["height"]) == (20, 60)
    stored = client.get(f"/api/v1/uploads/{body['id']}/file").content
    with Image.open(io.BytesIO(stored)) as out:
        assert not out.getexif()


def test_upload_rejects_non_images(client: TestClient) -> None:
    r = _upload(client, b"MZ\x90\x00 not an image", "evil.png")
    assert r.status_code == 415
    assert r.json()["error"]["code"] == "invalid_image"


def test_references_need_a_capable_model(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    ref = _upload(client, _png()).json()["id"]
    r = _job(client, references=[ref])
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "references_unsupported"


def test_missing_input_rejected(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    assert _job(client, variation_of=SOME_ID).json()["error"]["code"] == "input_not_found"


def test_reference_job_sends_pictures_to_engine(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    refs = [_upload(client, _png(30 + i)).json()["id"] for i in range(2)]
    job = _job(
        client, model="flux2-klein-4b", prompt="in this style", references=refs, enhance=True
    ).json()
    done = _wait(client, job["id"])
    assert done["status"] == "succeeded", done
    fake = services.engine.client  # type: ignore[attr-defined]
    assert sorted(fake.uploads) == sorted(f"photo-{r}.png" for r in refs)
    image = client.get(f"/api/v1/images/{done['image_ids'][0]}").json()
    assert image["final_prompt"] == "Enhanced: a vivid scene"
    assert image["params"]["references"] == refs


def test_variation_of_a_gallery_image(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    source = _wait(client, _job(client).json()["id"])["image_ids"][0]
    job = _job(client, variation_of=source, variation_strength=0.3).json()
    assert _wait(client, job["id"])["status"] == "succeeded"
    graph = services.engine.client.graphs[-1]  # type: ignore[attr-defined]
    assert any(n["class_type"] == "LoadImage" for n in graph.values())


def test_enhance_endpoint(client: TestClient, services: Services) -> None:
    r = client.post("/api/v1/prompt/enhance", json={"prompt": "кот"})
    assert r.json()["error"]["code"] == "enhancer_unavailable"
    install_fake_model(services)
    r = client.post("/api/v1/prompt/enhance", json={"prompt": "кот", "style": "anime"})
    assert r.status_code == 200
    assert r.json() == {"prompt": "Enhanced: a vivid scene"}


def test_models_expose_features(client: TestClient) -> None:
    models = {m["id"]: m for m in client.get("/api/v1/models").json()["models"]}
    assert models["flux2-klein-4b"]["features"] == {
        "references": True,
        "variation": False,
        "detail": False,
    }
    assert models["z-image-turbo"]["features"]["variation"] is True


def test_styles_endpoint(client: TestClient) -> None:
    assert len(client.get("/api/v1/styles").json()["styles"]) == len(STYLES)


def test_unknown_style_rejected(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    assert _job(client, style="nope").json()["error"]["code"] == "unknown_style"
