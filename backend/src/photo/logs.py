"""Logging: human-readable console plus a rotating file under data/logs."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        logs_dir / "photo.log", maxBytes=5 * 2**20, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))

    root = logging.getLogger()
    root.handlers[:] = [file_handler, console]
    root.setLevel(level)
    # httpx logs every request at INFO; that is noise for users.
    logging.getLogger("httpx").setLevel(logging.WARNING)
