"""Maximum quality routing and Enlarge 2x (model upscale + tiled detail pass)."""

from __future__ import annotations

import itertools

import pytest
from fastapi.testclient import TestClient

from photo import editing
from photo.api.app import Services
from photo.auto import route
from photo.catalog import default_catalog
from photo.engine.pipelines import QUALITY_NEGATIVE, build
from photo.schemas import GenerateParams

from .conftest import install_fake_model
from .test_api import wait_for
from .test_editing import noisy, upload

ALL = ["z-image-turbo", "flux2-klein-4b", "flux2-klein-4b-base"]


def test_max_quality_prefers_the_undistilled_model() -> None:
    assert route("photo", ALL, "max") == "flux2-klein-4b-base"
    assert route("anime", ALL, "max") == "flux2-klein-4b-base"
    # Graphics and 3D stay on Z-Image either way.
    assert route("graphic", ALL, "max") == "z-image-turbo"
    # Not installed: falls back to the fast model.
    assert route("photo", ["z-image-turbo", "flux2-klein-4b"], "max") == "flux2-klein-4b"


def test_fast_quality_never_picks_the_slow_model() -> None:
    assert route("photo", ALL, "fast") == "flux2-klein-4b"
    assert route("photo", ["flux2-klein-4b-base", "z-image-turbo"], "fast") == "z-image-turbo"


def test_undistilled_graph_uses_real_guidance_and_a_negative_prompt() -> None:
    spec = default_catalog().get("flux2-klein-4b-base")
    p = GenerateParams(model=spec.id, prompt="a lake")
    api = build(p, spec, spec.variant_files(spec.variant("nvfp4")), 1, "x").graph.to_api()
    texts = [n["inputs"]["text"] for n in api.values() if n["class_type"] == "CLIPTextEncode"]
    assert QUALITY_NEGATIVE in texts
    guider = next(n["inputs"] for n in api.values() if n["class_type"] == "CFGGuider")
    sched = next(n["inputs"] for n in api.values() if n["class_type"] == "Flux2Scheduler")
    assert guider["cfg"] == 5.0 and sched["steps"] == 20


# ---- tiles --------------------------------------------------------------------------


@pytest.mark.parametrize(("total", "tile"), [(3168, 1536), (1536, 1536), (800, 1536), (4096, 1536)])
def test_tiles_cover_everything_and_overlap(total: int, tile: int) -> None:
    starts = editing.tile_positions(total, min(tile, total), 256)
    size = min(tile, total)
    assert starts[0] == 0 and starts[-1] + size == total
    for a, b in itertools.pairwise(starts):
        assert b - a <= size - 256  # every seam has at least the full overlap


def test_tile_mask_ramps_only_on_shared_edges() -> None:
    m = editing.tile_mask(64, 48, 16, left=True, top=False)
    assert m.getpixel((0, 20)) < 32 and m.getpixel((40, 20)) == 255 and m.getpixel((40, 0)) == 255
    m = editing.tile_mask(64, 48, 16, left=False, top=True)
    assert m.getpixel((40, 0)) < 32 and m.getpixel((0, 40)) == 255
    assert editing.tile_mask(64, 48, 16, left=False, top=False).getextrema() == (255, 255)


def test_upscale_size() -> None:
    assert editing.upscale_size(1584, 1584) == (3168, 3168)
    w, h = editing.upscale_size(3000, 2000)  # type: ignore[misc]
    assert max(w, h) <= editing.MAX_UPSCALE_SIDE and w % 16 == 0 and h % 16 == 0
    assert editing.upscale_size(4000, 3000) is None


# ---- jobs ---------------------------------------------------------------------------


def test_auto_max_quality_job_runs_on_the_undistilled_model(
    client: TestClient, services: Services
) -> None:
    for model in ("z-image-turbo", "flux2-klein-4b", "flux2-klein-4b-base"):
        install_fake_model(services, model, "nvfp4")
    fake = services.engine.client  # type: ignore[attr-defined]
    fake.classify_answer = "photo | a mountain lake at dawn"
    body = {
        "model": "auto",
        "style": "auto",
        "quality": "max",
        "prompt": "озеро",
        "width": 768,
        "height": 768,
    }
    done = wait_for(client, client.post("/api/v1/jobs", json=body).json()["id"], "succeeded")
    assert done["model"] == "flux2-klein-4b-base"


def test_enlarge_runs_upscaler_then_tiles(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    install_fake_model(services, "real-esrgan-x4", "default")
    src = upload(client, noisy((600, 400)))
    done = wait_for(
        client,
        client.post(
            "/api/v1/jobs", json={"kind": "edit", "action": "upscale", "source": src}
        ).json()["id"],
        "succeeded",
    )
    graphs = services.engine.client.graphs  # type: ignore[attr-defined]
    kinds = [{n["class_type"] for n in g.values()} for g in graphs]
    assert "ImageUpscaleWithModel" in kinds[0]
    tiles = kinds[1:]
    assert tiles and all("SplitSigmasDenoise" in k for k in tiles)
    assert done["model"] == "flux2-klein-4b"


def test_enlarge_needs_the_upscaler(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    src = upload(client, noisy((600, 400)))
    r = client.post("/api/v1/jobs", json={"kind": "edit", "action": "upscale", "source": src})
    assert r.status_code == 409 and r.json()["error"]["code"] == "upscaler_missing"


def test_detail_prompt_comes_from_the_picture(client: TestClient, services: Services) -> None:
    assert "photograph" in services.jobs._prompt_for("01m70zzfvv9d8frsexpr8jtga9")
