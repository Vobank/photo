"""Pixel work around AI edits: masks, crop-and-stitch, and non-AI obscuring.

An area edit never lets the model touch pixels outside the user's selection:

1. the selection's bounding box is expanded with surrounding context and cropped;
2. the crop is scaled to the model's working size (~1 MP), which also gives small
   selections (a face in a crowd) far more pixels to work with;
3. the model's result is scaled back and blended in through a feathered copy of the
   selection, so only the selected area changes and the seam is invisible.

Obscuring (blur, pixelate, solid fill) needs no model at all and is exact.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageFilter, ImageOps

Box = tuple[int, int, int, int]  # left, top, right, bottom
ObscureMode = Literal["blur", "pixelate", "fill"]

# Context kept around the selection, as a fraction of the selection's larger side.
CONTEXT = 0.6
MIN_CROP_SIDE = 384
WORK_PIXELS = 1024 * 1024
MAX_SIDE = 2048


class EmptyMaskError(ValueError):
    """The selection is empty."""


def load_mask(data: bytes, size: tuple[int, int]) -> Image.Image:
    """A user-drawn selection as an 8-bit mask the size of the picture (white = edit).

    Accepts black/white or alpha-only PNGs; a different size is scaled to fit.
    """
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        if src.mode in ("RGBA", "LA") and src.getchannel("A").getextrema() != (255, 255):
            mask = src.getchannel("A")
        else:
            mask = src.convert("L")
    if mask.size != size:
        mask = mask.resize(size, Image.Resampling.BILINEAR)
    return mask.point(lambda v: 255 if v >= 128 else 0)


def bbox(mask: Image.Image) -> Box:
    box = mask.getbbox()
    if box is None:
        raise EmptyMaskError("nothing is selected")
    return box


def crop_box(size: tuple[int, int], selection: Box) -> Box:
    """Selection plus context, at least MIN_CROP_SIDE, kept inside the picture."""
    width, height = size
    left, top, right, bottom = selection
    pad = round(max(right - left, bottom - top) * CONTEXT)
    left, top, right, bottom = left - pad, top - pad, right + pad, bottom + pad

    def grow(lo: int, hi: int, limit: int, minimum: int) -> tuple[int, int]:
        need = min(minimum, limit) - (hi - lo)
        if need > 0:
            lo -= need // 2
            hi += need - need // 2
        # Slide the window back inside the picture without shrinking it.
        if lo < 0:
            hi, lo = hi - lo, 0
        if hi > limit:
            lo, hi = max(0, lo - (hi - limit)), limit
        return lo, hi

    left, right = grow(left, right, width, MIN_CROP_SIDE)
    top, bottom = grow(top, bottom, height, MIN_CROP_SIDE)
    return left, top, right, bottom


def work_size(width: int, height: int, pixels: int = WORK_PIXELS) -> tuple[int, int]:
    """Size the model works at: about ``pixels``, same shape, multiples of 16."""
    scale = math.sqrt(pixels / (width * height))
    scale = min(scale, MAX_SIDE / max(width, height))  # very long, thin pictures
    return (
        max(256, min(MAX_SIDE, round(width * scale / 16) * 16)),
        max(256, min(MAX_SIDE, round(height * scale / 16) * 16)),
    )


@dataclass(frozen=True, slots=True)
class Crop:
    box: Box  # where the crop sits in the source picture
    image: Image.Image  # crop scaled to work size, RGB
    mask: Image.Image  # selection inside the crop, at work size, L


def prepare(source: Image.Image, mask: Image.Image) -> Crop:
    box = crop_box(source.size, bbox(mask))
    size = work_size(box[2] - box[0], box[3] - box[1])
    image = source.convert("RGB").crop(box).resize(size, Image.Resampling.LANCZOS)
    return Crop(box, image, mask.crop(box).resize(size, Image.Resampling.BILINEAR))


def feather_radius(box: Box) -> int:
    return max(3, round(math.hypot(box[2] - box[0], box[3] - box[1]) * 0.012))


def soft_mask(mask: Image.Image, radius: int) -> Image.Image:
    """Grow the selection a little, then blur it, so the blend has no hard edge."""
    grow = radius * 2 + 1
    soft = mask.filter(ImageFilter.MaxFilter(min(grow, 31) | 1)).filter(
        ImageFilter.GaussianBlur(radius)
    )
    # Cut the blur's faint tail so the area of influence ends at a known distance:
    # beyond it the picture is guaranteed bit-identical.
    return soft.point(lambda v: 0 if v < 8 else v)


def influence(radius: int) -> int:
    """How far outside the selection a blend with ``radius`` can change pixels."""
    return min(radius * 2 + 1, 31) // 2 + radius * 3


def stitch(source: Image.Image, edited: Image.Image, mask: Image.Image, box: Box) -> Image.Image:
    """Blend the model's crop back into the full-size source inside the selection."""
    out = source.convert("RGB")
    size = (box[2] - box[0], box[3] - box[1])
    patch = edited.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    blend = soft_mask(mask.crop(box), feather_radius(box))
    region = Image.composite(patch, out.crop(box), blend)
    out.paste(region, box[:2])
    return out


def obscure(source: Image.Image, mask: Image.Image, mode: ObscureMode) -> Image.Image:
    """Hide the selection without AI: strong blur, coarse pixels or a flat fill.

    Strong enough that faces and text cannot be recovered by sharpening.
    """
    img = source.convert("RGB")
    left, top, right, bottom = bbox(mask)
    side = max(right - left, bottom - top)
    if mode == "blur":
        hidden = img.filter(ImageFilter.GaussianBlur(max(12, side // 6)))
    elif mode == "pixelate":
        cells = max(4, min(12, side // 24))
        block = max(8, side // cells)
        small = img.resize(
            (max(1, img.width // block), max(1, img.height // block)), Image.Resampling.BILINEAR
        )
        hidden = small.resize(img.size, Image.Resampling.NEAREST)
    else:
        # The selection's average colour: unobtrusive, like a censor bar that fits in.
        mean = ImageOps.fit(img.crop((left, top, right, bottom)), (1, 1)).getpixel((0, 0))
        hidden = Image.new("RGB", img.size, mean)
    edge = soft_mask(mask, 2) if mode != "fill" else mask
    return Image.composite(hidden, img, edge)
