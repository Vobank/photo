"""Editing: pixel guarantees (crop, stitch, obscure) and the edit job flow."""

from __future__ import annotations

import io
import random

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from photo import editing, edits
from photo.api.app import Services
from photo.schemas import EditParams

from .conftest import install_fake_model
from .test_api import wait_for

# ---- helpers -------------------------------------------------------------------------


def noisy(size: tuple[int, int] = (320, 240), seed: int = 1) -> Image.Image:
    """A picture with detail everywhere, so any unwanted change is visible."""
    rnd = random.Random(seed)
    return Image.frombytes("RGB", size, rnd.randbytes(size[0] * size[1] * 3))


def box_mask(size: tuple[int, int], box: tuple[int, int, int, int]) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle(box, fill=255)
    return mask


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def changed_outside(before: Image.Image, after: Image.Image, mask: Image.Image, margin: int) -> int:
    guard = mask.filter(ImageFilter.MaxFilter(margin * 2 + 1))
    diff = ImageChops.difference(before.convert("RGB"), after.convert("RGB")).convert("L")
    return ImageChops.multiply(diff, ImageChops.invert(guard)).getextrema()[1]


# ---- pixel work ----------------------------------------------------------------------


def test_crop_box_adds_context_and_stays_inside() -> None:
    box = editing.crop_box((1000, 800), (900, 700, 990, 790))
    left, top, right, bottom = box
    assert 0 <= left < 900 and 0 <= top < 700 and right <= 1000 and bottom <= 800
    assert right - left >= editing.MIN_CROP_SIDE and bottom - top >= editing.MIN_CROP_SIDE


def test_crop_box_on_small_picture_is_the_whole_picture() -> None:
    assert editing.crop_box((300, 200), (100, 50, 150, 100)) == (0, 0, 300, 200)


@pytest.mark.parametrize("size", [(4000, 3000), (300, 300), (6000, 400), (400, 6000)])
def test_work_size_is_always_valid_for_the_models(size: tuple[int, int]) -> None:
    w, h = editing.work_size(*size)
    assert w % 16 == 0 and h % 16 == 0
    assert 256 <= w <= 2048 and 256 <= h <= 2048
    assert w * h <= 2048 * 2048


def test_stitch_changes_only_the_selection() -> None:
    src = noisy()
    mask = box_mask(src.size, (100, 80, 180, 150))
    crop = editing.prepare(src, mask)
    edited = Image.new("RGB", crop.image.size, (255, 0, 0))
    out = editing.stitch(src, edited, mask, crop.box)
    margin = editing.influence(editing.feather_radius(crop.box))
    assert changed_outside(src, out, mask, margin) == 0
    # Inside, the edit took over.
    assert out.getpixel((140, 115)) == (255, 0, 0)


def test_empty_selection_is_rejected() -> None:
    with pytest.raises(editing.EmptyMaskError):
        editing.prepare(noisy(), Image.new("L", (320, 240), 0))


@pytest.mark.parametrize("mode", ["blur", "pixelate", "fill"])
def test_obscure_hides_the_selection_and_nothing_else(mode: editing.ObscureMode) -> None:
    src = noisy()
    region = (60, 40, 200, 180)
    mask = box_mask(src.size, region)
    out = editing.obscure(src, mask, mode)
    assert changed_outside(src, out, mask, editing.influence(2)) == 0
    inner = (90, 70, 170, 150)
    # Detail inside is gone: neighbouring pixels are now nearly identical.
    before = ImageChops.difference(
        src.crop(inner), src.crop(inner).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    )
    after = ImageChops.difference(
        out.crop(inner), out.crop(inner).transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    )
    mean = lambda im: sum(im.convert("L").tobytes()) / (im.width * im.height)  # noqa: E731
    assert mean(after) < mean(before) / 3


def test_load_mask_accepts_alpha_and_other_sizes() -> None:
    rgba = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    ImageDraw.Draw(rgba).rectangle((10, 10, 40, 40), fill=(255, 255, 255, 255))
    mask = editing.load_mask(png(rgba), (200, 100))
    assert mask.size == (200, 100)
    assert mask.getpixel((50, 50)) == 255 and mask.getpixel((150, 50)) == 0
    assert set(mask.tobytes()) <= {0, 255}


# ---- instructions --------------------------------------------------------------------


def test_instructions() -> None:
    src = "01m70zzfvv9d8frsexpr8jtga9"
    whole = EditParams(source=src, prompt="make it winter")
    assert edits.instruction(whole, "make it winter") == "make it winter."
    area = EditParams(source=src, mask=src, prompt="x")
    assert edits.instruction(area, "a red hat.").endswith("Keep everything else unchanged.")
    remove = EditParams(source=src, mask=src, action="remove")
    assert "the selected object" in edits.instruction(remove, "")
    named = EditParams(source=src, mask=src, action="remove", prompt="лодку")
    assert edits.instruction(named, "the boat").startswith("Remove the boat completely")


def test_translation_cleanup() -> None:
    assert edits.needs_translation("убери лодку") and not edits.needs_translation("remove the boat")
    assert edits.clean_translation('"Remove the boat"', "убери лодку") == "Remove the boat"
    assert edits.clean_translation("", "убери лодку") == "убери лодку"
    assert edits.clean_translation("x", "убери лодку с воды") == "убери лодку с воды"


@pytest.mark.parametrize(
    "bad",
    [
        {"action": "blur"},  # hiding needs a selection
        {"action": "edit"},  # editing needs words
        {"action": "remove"},  # removing needs a selection or a name
        {"action": "explode", "prompt": "x"},
    ],
)
def test_invalid_edit_params(bad: dict) -> None:
    with pytest.raises(ValueError):
        EditParams(source="01m70zzfvv9d8frsexpr8jtga9", **bad)


# ---- job flow ------------------------------------------------------------------------


def upload(client: TestClient, img: Image.Image) -> str:
    r = client.post("/api/v1/uploads", files={"file": ("p.png", png(img), "image/png")})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def image_file(client: TestClient, image_id: str) -> Image.Image:
    return Image.open(io.BytesIO(client.get(f"/api/v1/images/{image_id}/file").content)).convert(
        "RGB"
    )


def test_blur_runs_without_the_engine(client: TestClient, services: Services) -> None:
    src = noisy()
    mask = box_mask(src.size, (60, 40, 200, 180))
    body = {
        "kind": "edit",
        "action": "blur",
        "source": upload(client, src),
        "mask": upload(client, mask.convert("RGB")),
    }
    done = wait_for(client, client.post("/api/v1/jobs", json=body).json()["id"], "succeeded")
    assert done["model"] == "tools"
    assert services.engine.client.graphs == []  # type: ignore[attr-defined]
    out = image_file(client, done["image_ids"][0])
    assert out.size == src.size
    assert changed_outside(src, out, mask, editing.influence(2)) == 0
    info = client.get(f"/api/v1/images/{done['image_ids'][0]}").json()
    assert info["source"] == body["source"] and info["params"]["kind"] == "edit"


def test_area_edit_keeps_everything_outside(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    src = noisy((512, 384))
    mask = box_mask(src.size, (200, 150, 300, 230))
    body = {
        "kind": "edit",
        "source": upload(client, src),
        "mask": upload(client, mask.convert("RGB")),
        "prompt": "a red hat",
        "batch_size": 2,
    }
    done = wait_for(client, client.post("/api/v1/jobs", json=body).json()["id"], "succeeded")
    assert done["model"] == "flux2-klein-4b"
    assert len(done["image_ids"]) == 2
    graph = services.engine.client.graphs[-1]  # type: ignore[attr-defined]
    types = [n["class_type"] for n in graph.values()]
    assert "ReferenceLatent" in types  # edits always see the picture
    text = next(n["inputs"]["text"] for n in graph.values() if n["class_type"] == "CLIPTextEncode")
    assert text == "a red hat. Keep everything else unchanged."
    out = image_file(client, done["image_ids"][0])
    assert out.size == src.size  # full resolution kept
    crop_box = editing.crop_box(src.size, (200, 150, 301, 231))
    assert changed_outside(src, out, mask, editing.influence(editing.feather_radius(crop_box))) == 0


def test_whole_picture_edit_and_russian_instruction(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    install_fake_model(services, "z-image-turbo", "nvfp4")  # provides the language model
    body = {"kind": "edit", "source": upload(client, noisy()), "prompt": "сделай зиму"}
    done = wait_for(client, client.post("/api/v1/jobs", json=body).json()["id"], "succeeded")
    fake = services.engine.client  # type: ignore[attr-defined]
    assert len(fake.graphs) == 2  # translation, then the edit
    text = next(
        n["inputs"]["text"] for n in fake.graphs[-1].values() if n["class_type"] == "CLIPTextEncode"
    )
    assert text == "Enhanced: a vivid scene."  # the fake engine's "translation"
    info = client.get(f"/api/v1/images/{done['image_ids'][0]}").json()
    assert info["final_prompt"] == text
    assert info["params"]["prompt"] == "сделай зиму"


def test_editing_needs_an_edit_capable_model(client: TestClient, services: Services) -> None:
    install_fake_model(services, "z-image-turbo", "nvfp4")
    body = {"kind": "edit", "source": upload(client, noisy()), "prompt": "make it winter"}
    r = client.post("/api/v1/jobs", json=body)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "edit_model_missing"


def test_missing_source_is_rejected(client: TestClient, services: Services) -> None:
    install_fake_model(services, "flux2-klein-4b", "nvfp4")
    r = client.post(
        "/api/v1/jobs", json={"kind": "edit", "source": "01m70zzfvv9d8frsexpr8jtga9", "prompt": "x"}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "input_not_found"


def test_empty_selection_fails_politely(client: TestClient, services: Services) -> None:
    src = noisy()
    body = {
        "kind": "edit",
        "action": "pixelate",
        "source": upload(client, src),
        "mask": upload(client, Image.new("RGB", src.size)),
    }
    done = wait_for(client, client.post("/api/v1/jobs", json=body).json()["id"], "failed")
    assert done["error_code"] == "empty_selection"


def test_edit_validation_errors_use_plain_field_names(client: TestClient) -> None:
    r = client.post("/api/v1/jobs", json={"kind": "edit", "source": "nope", "prompt": "x"})
    assert r.status_code == 422
    assert "source" in {f["field"] for f in r.json()["error"]["fields"]}
