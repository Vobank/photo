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

from PIL import Image, PngImagePlugin

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
