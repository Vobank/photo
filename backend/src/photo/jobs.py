"""Job queue: persistence, the single GPU worker, cancellation and crash recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from photo import storage
from photo.catalog import Catalog, ModelSpec, Variant, is_installed
from photo.config import Settings
from photo.db import Database
from photo.engine import pipelines
from photo.engine.client import (
    EngineError,
    EngineInterrupted,
    EngineUnavailable,
    Preview,
    Progress,
)
from photo.engine.process import EngineProcess, EngineState
from photo.events import EventBus
from photo.hardware import Gpu
from photo.ids import new_id
from photo.schemas import MAX_SEED, TERMINAL_STATUSES, GenerateParams, JobParams, JobStatus

log = logging.getLogger(__name__)


class JobRejected(Exception):
    """The request is valid but cannot run (e.g. model not installed)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    kind: str
    status: JobStatus
    params: dict[str, Any]
    model: str
    variant: str
    seed: int
    progress: float
    error: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None
    image_ids: tuple[str, ...] = ()

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "params": self.params,
            "model": self.model,
            "variant": self.variant,
            "seed": self.seed,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "image_ids": list(self.image_ids),
        }


def friendly_error(exc: BaseException) -> str:
    text = str(exc)
    low = text.lower()
    if "out of memory" in low or "outofmemory" in low:
        return (
            "Not enough video memory for this request. Try a smaller size or batch, "
            "or close other programs that use the GPU."
        )
    if isinstance(exc, EngineUnavailable):
        return "The engine is not running. It is being restarted; try again in a moment."
    return text or exc.__class__.__name__


def installed_variant(settings: Settings, spec: ModelSpec, gpu: Gpu | None) -> Variant | None:
    """The preferred variant for this GPU if installed, else any installed variant."""
    preferred = spec.choose_variant(gpu)
    ordered = [preferred, *(v for v in spec.variants if v is not preferred)]
    for v in ordered:
        if all(is_installed(settings.models, f) for f in spec.variant_files(v).values()):
            return v
    return None


class JobService:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        catalog: Catalog,
        engine: EngineProcess,
        bus: EventBus,
        gpu: Gpu | None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.catalog = catalog
        self.engine = engine
        self.bus = bus
        self.gpu = gpu
        self._wakeup = asyncio.Event()
        self._worker: asyncio.Task[None] | None = None
        self._running_id: str | None = None
        self._cancel_requested: set[str] = set()

    # ---- lifecycle -----------------------------------------------------------------

    def recover(self) -> int:
        """Fail jobs a previous process left mid-flight. Returns how many."""
        return self.db.execute(
            "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE status='running'",
            ("Interrupted: the app was closed while this job was running.", time.time()),
        )

    def start(self) -> None:
        self._worker = asyncio.create_task(self._work_loop(), name="job-worker")

    async def stop(self) -> None:
        if self._worker:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    # ---- queries -------------------------------------------------------------------

    def _row_to_job(self, row: Any) -> Job:
        images = self.db.all(
            "SELECT id FROM images WHERE job_id=? AND deleted_at IS NULL ORDER BY id", (row["id"],)
        )
        return Job(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            params=json.loads(row["params"]),
            model=row["model"],
            variant=row["variant"],
            seed=row["seed"],
            progress=row["progress"],
            error=row["error"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            image_ids=tuple(r["id"] for r in images),
        )

    def get(self, job_id: str) -> Job | None:
        row = self.db.one("SELECT * FROM jobs WHERE id=?", (job_id,))
        return self._row_to_job(row) if row else None

    def list_jobs(self, limit: int = 50, active_only: bool = False) -> list[Job]:
        where = "WHERE status IN ('queued','running')" if active_only else ""
        rows = self.db.all(f"SELECT * FROM jobs {where} ORDER BY id DESC LIMIT ?", (limit,))  # noqa: S608
        return [self._row_to_job(r) for r in rows]

    # ---- commands ------------------------------------------------------------------

    def submit(self, params: JobParams) -> Job:
        try:
            spec = self.catalog.get(params.model)
        except KeyError:
            raise JobRejected("unknown_model", f"Unknown model {params.model!r}.") from None
        if params.kind not in spec.tasks:
            raise JobRejected("unsupported_task", f"{spec.name} cannot do {params.kind!r}.")
        variant = installed_variant(self.settings, spec, self.gpu)
        if variant is None:
            raise JobRejected(
                "model_not_installed", f"{spec.name} is not downloaded yet. Install it first."
            )
        if self.engine.state is EngineState.NOT_INSTALLED:
            raise JobRejected("engine_not_installed", self.engine.last_error or "Engine missing.")

        seed = params.seed if params.seed is not None else secrets.randbelow(MAX_SEED + 1)
        job_id = new_id()
        now = time.time()
        self.db.execute(
            "INSERT INTO jobs (id, kind, status, params, model, variant, seed, created_at) "
            "VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)",
            (job_id, params.kind, params.model_dump_json(), spec.id, variant.id, seed, now),
        )
        job = self.get(job_id)
        assert job is not None
        self.bus.publish("job", {"job": job.to_api()})
        self._wakeup.set()
        return job

    async def cancel(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if job is None or job.status in TERMINAL_STATUSES:
            return job
        if job.status == "queued":
            self._finish(job_id, "cancelled", None)
        else:
            self._cancel_requested.add(job_id)
            if self.engine.client:
                await self.engine.client.interrupt()
        return self.get(job_id)

    # ---- worker --------------------------------------------------------------------

    def _next_queued(self) -> Job | None:
        row = self.db.one("SELECT * FROM jobs WHERE status='queued' ORDER BY id LIMIT 1")
        return self._row_to_job(row) if row else None

    def _finish(self, job_id: str, status: JobStatus, error: str | None) -> None:
        self.db.execute(
            "UPDATE jobs SET status=?, error=?, finished_at=?, "
            "progress=CASE WHEN ?='succeeded' THEN 1 ELSE progress END WHERE id=?",
            (status, error, time.time(), status, job_id),
        )
        job = self.get(job_id)
        if job:
            self.bus.publish("job", {"job": job.to_api()})

    async def _work_loop(self) -> None:
        while True:
            job = self._next_queued()
            if job is None:
                self._wakeup.clear()
                await self._wakeup.wait()
                continue
            try:
                await self._run(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # never let one job kill the worker
                log.exception("job %s crashed the worker step", job.id)
                self._finish(job.id, "failed", friendly_error(exc))

    async def _run(self, job: Job) -> None:
        if self.engine.state is EngineState.NOT_INSTALLED:
            self._finish(job.id, "failed", self.engine.last_error)
            return
        client = await self.engine.wait_ready()

        # The job may have been cancelled while we waited for the engine.
        claimed = self.db.execute(
            "UPDATE jobs SET status='running', started_at=? WHERE id=? AND status='queued'",
            (time.time(), job.id),
        )
        if not claimed:
            return
        self._running_id = job.id
        running = self.get(job.id)
        assert running is not None
        self.bus.publish("job", {"job": running.to_api()})

        spec = self.catalog.get(job.model)
        variant = spec.variant(job.variant)
        params = GenerateParams.model_validate(job.params)
        built = pipelines.build(
            params, spec, spec.variant_files(variant), job.seed, f"photo/{job.id}"
        )

        last_progress = 0.0

        async def on_progress(p: Progress) -> None:
            nonlocal last_progress
            frac = p.value / p.max if p.max else 0.0
            if frac - last_progress >= 0.01 or frac >= 1:
                last_progress = frac
                self.db.execute("UPDATE jobs SET progress=? WHERE id=?", (frac, job.id))
                self.bus.publish("progress", {"job_id": job.id, "value": p.value, "max": p.max})

        async def on_preview(pv: Preview) -> None:
            self.bus.publish_preview(job.id, pv.mime, pv.data)

        try:
            result = await client.run(
                built.graph.to_api(),
                built.output_node,
                on_progress=on_progress,
                on_preview=on_preview,
            )
            if not result.images:
                raise EngineError("The engine finished without producing an image.")
            blobs = [await client.fetch_image(img) for img in result.images]
            await self._store_outputs(job, spec, variant, params, blobs)
        except EngineInterrupted:
            self._finish(job.id, "cancelled", None)
            return
        except (EngineError, EngineUnavailable) as exc:
            if job.id in self._cancel_requested:
                self._finish(job.id, "cancelled", None)
            else:
                details = getattr(exc, "details", "")
                log.error("job %s failed: %s\n%s", job.id, exc, details)
                self._finish(job.id, "failed", friendly_error(exc))
            return
        finally:
            self._running_id = None
            self._cancel_requested.discard(job.id)

        self._finish(job.id, "succeeded", None)

    async def _store_outputs(
        self,
        job: Job,
        spec: ModelSpec,
        variant: Variant,
        params: GenerateParams,
        blobs: list[bytes],
    ) -> None:
        d = spec.defaults
        for index, raw in enumerate(blobs):
            image_id = new_id()
            meta = {
                "schema": 1,
                "params": params.model_dump(),
                "seed": job.seed,
                "batch_index": index,
                "steps": params.steps or d.steps,
                "cfg": params.cfg if params.cfg is not None else d.cfg,
                "model_variant": variant.id,
            }
            stored = await asyncio.to_thread(
                storage.save_result, self.settings.images_dir, image_id, raw, meta
            )
            self.db.execute(
                "INSERT INTO images (id, job_id, path, thumb_path, width, height, seed, model, "
                "params, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    stored.id, job.id, stored.path, stored.thumb_path, stored.width,
                    stored.height, job.seed, spec.id, json.dumps(meta), time.time(),
                ),
            )  # fmt: skip
            self.bus.publish("image", {"image_id": image_id, "job_id": job.id})
