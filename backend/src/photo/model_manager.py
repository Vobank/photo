"""Model install state and background downloads, shared by the API and the CLI."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from photo.catalog import Catalog, ModelFile, ModelSpec, Variant, is_installed
from photo.config import Settings
from photo.downloads import DownloadError, DownloadRequest, download
from photo.events import EventBus
from photo.hardware import Gpu

log = logging.getLogger(__name__)


@dataclass
class InstallTask:
    model_id: str
    variant_id: str
    total: int
    done: int = 0
    error: str | None = None
    finished: bool = False
    started_at: float = field(default_factory=time.time)

    def to_api(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "variant_id": self.variant_id,
            "total": self.total,
            "done": self.done,
            "error": self.error,
            "finished": self.finished,
        }


def missing_files(settings: Settings, spec: ModelSpec, variant: Variant) -> list[ModelFile]:
    return [f for f in spec.variant_files(variant).values() if not is_installed(settings.models, f)]


class ModelManager:
    def __init__(self, settings: Settings, catalog: Catalog, bus: EventBus, gpu: Gpu | None):
        self.settings = settings
        self.catalog = catalog
        self.bus = bus
        self.gpu = gpu
        self.tasks: dict[str, InstallTask] = {}
        self._running: dict[str, asyncio.Task[None]] = {}
        # One download stream at a time is fastest on most home connections and keeps
        # partial files to a minimum if the user quits midway.
        self._lock = asyncio.Lock()

    def describe(self, spec: ModelSpec) -> dict[str, Any]:
        recommended = spec.choose_variant(self.gpu)
        variants = []
        for v in spec.variants:
            files = spec.variant_files(v).values()
            variants.append({
                "id": v.id,
                "label": v.label,
                "fits_gpu": v.fits(self.gpu),
                "recommended": v is recommended,
                "installed": all(is_installed(self.settings.models, f) for f in files),
                "download_bytes": sum(f.size for f in missing_files(self.settings, spec, v)),
                "total_bytes": sum(f.size for f in files),
            })  # fmt: skip
        task = self.tasks.get(spec.id)
        return {
            "id": spec.id,
            "name": spec.name,
            "vendor": spec.vendor,
            "description": spec.description,
            "tasks": list(spec.tasks),
            "license": spec.license,
            "license_url": spec.license_url,
            "commercial_use": spec.commercial_use,
            "defaults": spec.defaults.model_dump(),
            "installed": any(v["installed"] for v in variants),
            "variants": variants,
            "install": task.to_api() if task and not task.finished else None,
        }

    def install(self, model_id: str, variant_id: str | None = None) -> InstallTask:
        spec = self.catalog.get(model_id)
        variant = spec.variant(variant_id) if variant_id else spec.choose_variant(self.gpu)
        current = self._running.get(model_id)
        if current and not current.done():
            return self.tasks[model_id]
        files = missing_files(self.settings, spec, variant)
        task = InstallTask(model_id, variant.id, total=sum(f.size for f in files))
        self.tasks[model_id] = task
        self._running[model_id] = asyncio.create_task(self._install(task, files))
        return task

    async def cancel(self, model_id: str) -> None:
        t = self._running.get(model_id)
        if t and not t.done():
            t.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await t

    async def _install(self, task: InstallTask, files: list[ModelFile]) -> None:
        last_emit = 0.0
        base = 0

        def on_progress(done: int, _total: int) -> None:
            nonlocal last_emit
            task.done = base + done
            now = time.monotonic()
            if now - last_emit >= 0.25:
                last_emit = now
                self.bus.publish("model_install", task.to_api())

        try:
            async with self._lock:
                for f in files:
                    req = DownloadRequest(
                        url=f.url(self.settings.hf_endpoint),
                        dest=self.settings.models / f.relative_path,
                        size=f.size,
                        sha256=f.sha256,
                        token=self.settings.hf_token,
                    )
                    log.info("downloading %s", f.name)
                    await download(req, on_progress)
                    base += f.size
        except asyncio.CancelledError:
            task.error = "cancelled"
            raise
        except DownloadError as exc:
            task.error = str(exc)
            log.error("install of %s failed: %s", task.model_id, exc)
        except OSError as exc:
            task.error = f"Disk error: {exc}"
            log.error("install of %s failed: %s", task.model_id, exc)
        finally:
            task.finished = True
            self.bus.publish("model_install", task.to_api())
