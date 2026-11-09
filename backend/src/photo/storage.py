"""Image files on disk.

Each result is re-encoded as PNG with our own metadata:

* ``photo`` — JSON with the exact parameters, so dropping the file back into the app
  reproduces it even if the database is gone.
* ``parameters`` — the de-facto text format many image tools and galleries read.

The engine's own graph metadata is dropped: it exposes internal file paths.
"""

from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, PngImagePlugin

from photo import __version__

THUMB_MAX = 384
METADATA_KEY = "photo"


@dataclass(frozen=True, slots=True)
class StoredImage:
    id: str
    path: str  # relative to images root, forward slashes
    thumb_path: str
    width: int
    height: int


def _human_parameters(meta: dict[str, Any]) -> str:
    p = meta.get("params", {})
    lines = [str(p.get("prompt", ""))]
    if p.get("negative_prompt"):
        lines.append(f"Negative prompt: {p['negative_prompt']}")
    lines.append(
        f"Steps: {meta.get('steps')}, CFG scale: {meta.get('cfg')}, Seed: {meta.get('seed')}, "
        f"Size: {p.get('width')}x{p.get('height')}, Model: {p.get('model')}, "
        f"Version: photo {__version__}"
    )
    return "\n".join(lines)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save_result(root: Path, image_id: str, raw: bytes, meta: dict[str, Any]) -> StoredImage:
    """Store one engine output. ``meta`` must be JSON-serialisable."""
    month = time.strftime("%Y/%m")
    folder = root / month
    folder.mkdir(parents=True, exist_ok=True)

    with Image.open(io.BytesIO(raw)) as src:
        src.load()
        img = src.convert("RGBA") if src.mode in ("RGBA", "LA", "P") else src.convert("RGB")

    info = PngImagePlugin.PngInfo()
    info.add_itxt(METADATA_KEY, json.dumps(meta, ensure_ascii=False, separators=(",", ":")))
    info.add_itxt("parameters", _human_parameters(meta))
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info, compress_level=4)
    _atomic_write(folder / f"{image_id}.png", buf.getvalue())

    thumb = img.copy()
    thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.Resampling.LANCZOS)
    tbuf = io.BytesIO()
    thumb.save(tbuf, format="WEBP", quality=82, method=4)
    _atomic_write(folder / f"{image_id}.thumb.webp", tbuf.getvalue())

    return StoredImage(
        id=image_id,
        path=f"{month}/{image_id}.png",
        thumb_path=f"{month}/{image_id}.thumb.webp",
        width=img.width,
        height=img.height,
    )


MAX_UPLOAD_BYTES = 50 * 2**20
MAX_UPLOAD_PIXELS = 64_000_000
# Inputs larger than this are scaled down: models work at ~1-4 MP anyway.
UPLOAD_MAX_SIDE = 3072


# Pillow raises DecompressionBombError above this: guards against tiny files that
# decode to gigantic images.
Image.MAX_IMAGE_PIXELS = MAX_UPLOAD_PIXELS


class InvalidImageError(ValueError):
    pass


def save_upload(root: Path, upload_id: str, raw: bytes) -> StoredImage:
    """Validate and normalise a user's picture: orientation applied, metadata (GPS,
    camera serials) dropped, transparency flattened onto white, stored as PNG."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidImageError("file too large")
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as src:
            src.load()
            img = ImageOps.exif_transpose(src)
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("not a supported image") from exc

    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        img = flat
    else:
        img = img.convert("RGB")
    if max(img.size) > UPLOAD_MAX_SIDE:
        img.thumbnail((UPLOAD_MAX_SIDE, UPLOAD_MAX_SIDE), Image.Resampling.LANCZOS)

    root.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=4)
    _atomic_write(root / f"{upload_id}.png", buf.getvalue())
    thumb = img.copy()
    thumb.thumbnail((THUMB_MAX, THUMB_MAX), Image.Resampling.LANCZOS)
    tbuf = io.BytesIO()
    thumb.save(tbuf, format="WEBP", quality=82, method=4)
    _atomic_write(root / f"{upload_id}.thumb.webp", tbuf.getvalue())
    return StoredImage(
        upload_id, f"{upload_id}.png", f"{upload_id}.thumb.webp", img.width, img.height
    )


def read_metadata(data: bytes) -> dict[str, Any] | None:
    """Parameters embedded by :func:`save_result`, or None for foreign images."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            text = getattr(img, "text", {}).get(METADATA_KEY)
    except (OSError, ValueError):
        return None
    if not text:
        return None
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def resolve(root: Path, relative: str) -> Path:
    """Map a stored relative path to disk, refusing anything outside ``root``."""
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ValueError("path escapes image root")
    return candidate
