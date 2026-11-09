"""Read-modify-write of ``photo.toml``, the user's persistent choices.

Only a small, known set of flat keys is ever written, so a tiny serialiser is enough
and keeps comments-free files predictable. Unknown keys a user added by hand survive.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from photo.config import config_file

type Value = str | int | float | bool | list[str]

WRITABLE_KEYS = frozenset({"language", "models_dir", "data_dir", "engine_env_dir"})


def _quote(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _render(value: Value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(_quote(v) for v in value) + "]"
    return _quote(value)


def read(path: Path | None = None) -> dict[str, Any]:
    path = path or config_file()
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        return {}


def update(values: Mapping[str, Value | Path | None], path: Path | None = None) -> Path:
    """Merge ``values`` into photo.toml atomically. ``None`` removes a key."""
    unknown = set(values) - WRITABLE_KEYS
    if unknown:
        raise ValueError(f"not writable: {sorted(unknown)}")
    path = path or config_file()
    data = read(path)
    for key, value in values.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = str(value) if isinstance(value, Path) else value

    lines = ["# Written by Photo. Safe to edit while Photo is closed."]
    for key in sorted(data):
        value = data[key]
        if isinstance(value, dict):
            continue  # tables are hand-written; we never produce them
        lines.append(f"{key} = {_render(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
