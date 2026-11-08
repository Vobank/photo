"""Resumable, verified file downloads.

A file is written to ``<name>.part`` and only renamed into place after its size and
SHA-256 match the catalog. Interrupted downloads resume from where they stopped,
across retries and across app restarts.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from photo import __version__

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, int], None]

_CHUNK = 1 << 20  # 1 MiB
_MAX_ATTEMPTS = 8
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class DownloadError(Exception):
    pass


class IntegrityError(DownloadError):
    pass


class NotEnoughSpaceError(DownloadError):
    pass


class _RetryableHTTPError(Exception):
    pass


class DownloadInProgressError(DownloadError):
    """Another process (e.g. the CLI while the app runs) is downloading this file."""


class _FileLock:
    """Exclusive, non-blocking OS lock; released automatically if the process dies."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: Any = None

    def acquire(self) -> bool:
        fh = self.path.open("a+b")
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._fh.close()
            self._fh = None
            self.path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class DownloadRequest:
    url: str
    dest: Path
    size: int
    sha256: str
    token: str | None = None


def free_bytes(path: Path) -> int:
    probe = path
    while not probe.exists():
        probe = probe.parent
    return shutil.disk_usage(probe).free


def ensure_space(dest_dir: Path, needed: int, margin: int = 2 << 30) -> None:
    free = free_bytes(dest_dir)
    if free < needed + margin:
        raise NotEnoughSpaceError(
            f"Need {(needed + margin) / 2**30:.1f} GiB free on the drive holding {dest_dir}, "
            f"only {free / 2**30:.1f} GiB available."
        )


def _hash_existing(path: Path) -> tuple[hashlib._Hash, int]:
    h = hashlib.sha256()
    n = 0
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK * 8):
            h.update(chunk)
            n += len(chunk)
    return h, n


def _part_size(part: Path) -> int:
    try:
        return part.stat().st_size
    except FileNotFoundError:
        return 0


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(connect=20, read=60, write=60, pool=20),
        headers={"User-Agent": f"photo/{__version__}"},
    )


async def download(
    req: DownloadRequest,
    progress: ProgressFn | None = None,
    client: httpx.AsyncClient | None = None,
) -> Path:
    """Download ``req`` to ``req.dest``. Returns the final path. Idempotent."""
    dest = req.dest
    if dest.exists() and dest.stat().st_size == req.size:
        if progress:
            progress(req.size, req.size)
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    lock = _FileLock(dest.with_name(dest.name + ".lock"))
    if not lock.acquire():
        raise DownloadInProgressError(
            f"{dest.name} is already being downloaded by another process."
        )
    try:
        return await _download_locked(req, part, progress, client)
    finally:
        lock.release()


async def _download_locked(
    req: DownloadRequest,
    part: Path,
    progress: ProgressFn | None,
    client: httpx.AsyncClient | None,
) -> Path:
    dest = req.dest
    own_client = client is None
    http = client or _client()
    try:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                await _download_once(http, req, part, progress)
                break
            except IntegrityError:
                await asyncio.to_thread(part.unlink, missing_ok=True)
                raise
            except (httpx.TransportError, _RetryableHTTPError) as exc:
                if attempt == _MAX_ATTEMPTS:
                    msg = f"{dest.name}: giving up after {attempt} attempts: {exc}"
                    raise DownloadError(msg) from exc
                delay = min(2**attempt, 60)
                log.warning("download %s failed (%s), retry in %ss", dest.name, exc, delay)
                await asyncio.sleep(delay)
    finally:
        if own_client:
            await http.aclose()

    os.replace(part, dest)
    return dest


async def _download_once(
    http: httpx.AsyncClient, req: DownloadRequest, part: Path, progress: ProgressFn | None
) -> None:
    existing = await asyncio.to_thread(_part_size, part)
    if existing > req.size:
        await asyncio.to_thread(part.unlink)
        existing = 0

    if existing:
        hasher, have = await asyncio.to_thread(_hash_existing, part)
    else:
        hasher, have = hashlib.sha256(), 0

    if have < req.size:
        ensure_space(part.parent, req.size - have)
        headers = {"Range": f"bytes={have}-"} if have else {}
        if req.token:
            headers["Authorization"] = f"Bearer {req.token}"

        async with http.stream("GET", req.url, headers=headers) as resp:
            if resp.status_code in _RETRYABLE_STATUS:
                raise _RetryableHTTPError(f"HTTP {resp.status_code}")
            if resp.status_code == 200 and have:
                # Server ignored Range: start over.
                hasher, have = hashlib.sha256(), 0
                mode = "wb"
            elif resp.status_code in (200, 206):
                mode = "ab" if have else "wb"
            elif resp.status_code in (401, 403):
                raise DownloadError(
                    f"{req.dest.name}: access denied (HTTP {resp.status_code}). "
                    "The model may require accepting its licence or an access token."
                )
            else:
                raise DownloadError(f"{req.dest.name}: HTTP {resp.status_code} from {req.url}")

            with part.open(mode) as fh:
                async for chunk in resp.aiter_bytes(_CHUNK):
                    fh.write(chunk)
                    hasher.update(chunk)
                    have += len(chunk)
                    if have > req.size:
                        raise IntegrityError(
                            f"{req.dest.name}: server sent more bytes than expected"
                        )
                    if progress:
                        progress(have, req.size)

    if have != req.size:
        raise _RetryableHTTPError(f"connection closed at {have}/{req.size} bytes")
    digest = hasher.hexdigest()
    if digest != req.sha256:
        raise IntegrityError(
            f"{req.dest.name}: checksum mismatch (expected {req.sha256[:12]}…, got {digest[:12]}…)"
        )
