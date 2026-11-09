"""Job queue: persistence, the single GPU worker, cancellation and crash recovery."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from photo import storage
from photo.auto import (
    AUTO,
    MEDIUM_STYLE,
    STYLE_MEDIUM,
    Classification,
    Medium,
    parse_classification,
    route,
)
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
from photo.styles import Style, apply_style, get_style

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
    error_code: str | None
    created_at: float
    started_at: float | None
    finished_at: float | None
    image_ids: tuple[str, ...] = ()
    # Automatic mode's decisions: {"medium", "style", "model", "prompt"}.
    resolved: dict[str, Any] | None = None

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
            "error_code": self.error_code,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "image_ids": list(self.image_ids),
            "resolved": self.resolved,
        }


def friendly_error(exc: BaseException) -> tuple[str, str]:
    """(code, English message). The UI translates by code and may show the message as detail."""
    text = str(exc)
    low = text.lower()
    if "out of memory" in low or "outofmemory" in low:
        return "out_of_memory", (
            "Not enough video memory for this request. Try a smaller size or batch, "
            "or close other programs that use the GPU."
        )
    if isinstance(exc, EngineUnavailable):
        return "engine_unavailable", (
            "The engine is not running. It is being restarted; try again in a moment."
        )
    return "engine_error", text or exc.__class__.__name__


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
            "UPDATE jobs SET status='failed', error=?, error_code='interrupted', finished_at=? "
            "WHERE status='running'",
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
            error_code=row["error_code"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            image_ids=tuple(r["id"] for r in images),
            resolved=json.loads(row["resolved"]) if row["resolved"] else None,
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
        if params.model == AUTO:
            # Provisional pick; the real one is made when the job runs (see _resolve_auto).
            candidates = self._candidates(params)
            if not candidates:
                raise JobRejected(
                    "model_not_installed", "No installed model can do this. Install one first."
                )
            provisional = STYLE_MEDIUM.get(params.style or "", "photo")
            spec = self.catalog.get(route(provisional, candidates) or candidates[0])
        else:
            try:
                spec = self.catalog.get(params.model)
            except KeyError:
                raise JobRejected("unknown_model", f"Unknown model {params.model!r}.") from None
        if params.kind not in spec.tasks:
            raise JobRejected("unsupported_task", f"{spec.name} cannot do {params.kind!r}.")
        self._check_features(spec, params)
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

    def _check_features(self, spec: ModelSpec, params: GenerateParams) -> None:
        caps = pipelines.capabilities(spec)
        if params.references and not caps.references:
            raise JobRejected(
                "references_unsupported", f"{spec.name} cannot follow reference images."
            )
        if params.variation_of and not caps.variation:
            raise JobRejected("variation_unsupported", f"{spec.name} cannot make variations.")
        # In automatic mode the detail pass is best effort: used when the chosen model has it.
        if params.detail and not caps.detail and params.model != AUTO:
            raise JobRejected("detail_unsupported", f"{spec.name} has no detail pass.")
        if params.style and params.style != AUTO and get_style(params.style) is None:
            raise JobRejected("unknown_style", f"Unknown style {params.style!r}.")
        for input_id in [
            *params.references,
            *([params.variation_of] if params.variation_of else []),
        ]:
            if self.input_path(input_id) is None:
                raise JobRejected("input_not_found", "A reference picture no longer exists.")

    def _candidates(self, params: GenerateParams) -> list[str]:
        """Installed models able to do what ``params`` strictly needs, in catalog order."""
        out: list[str] = []
        for spec in self.catalog.models:
            caps = pipelines.capabilities(spec)
            if (
                params.kind in spec.tasks
                and (caps.references or not params.references)
                and (caps.variation or not params.variation_of)
                and installed_variant(self.settings, spec, self.gpu) is not None
            ):
                out.append(spec.id)
        return out

    async def _classify(self, client: Any, prompt: str) -> Classification:
        """Medium + English prompt. Falls back to photo + the original text on any trouble."""
        fallback = Classification("photo", prompt, understood=False)
        name = self._writer_file()
        if name is None:
            return fallback
        built = pipelines.build_classify(name, prompt)
        try:
            result = await client.run(built.graph.to_api(), built.output_node)
        except (EngineError, EngineUnavailable) as exc:
            log.warning("automatic mode could not classify the request: %s", exc)
            return fallback
        return parse_classification(result.texts.get(built.output_node, ""), prompt)

    async def _resolve_auto(
        self, client: Any, job: Job, params: GenerateParams
    ) -> tuple[GenerateParams, ModelSpec, Variant, dict[str, Any]]:
        """Turn "auto" style/model into concrete choices and record them on the job."""
        update: dict[str, Any] = {}
        translated: str | None = None
        medium: Medium
        if params.style == AUTO:
            c = await self._classify(client, params.prompt)
            medium = c.medium
            update["style"] = MEDIUM_STYLE[medium]
            # With "enhance" on, the writer translates while it expands the prompt.
            if c.understood and not params.enhance:
                update["prompt"] = translated = c.prompt
        else:
            medium = STYLE_MEDIUM.get(params.style or "", "photo")

        model_id = params.model
        if model_id == AUTO:
            model_id = route(medium, self._candidates(params)) or job.model
        spec = self.catalog.get(model_id)
        variant = installed_variant(self.settings, spec, self.gpu) or spec.variant(job.variant)
        if params.detail and not pipelines.capabilities(spec).detail:
            update["detail"] = False
        update["model"] = spec.id

        resolved = {
            "medium": medium,
            "style": update.get("style", params.style),
            "model": spec.id,
            "prompt": translated,
        }
        self.db.execute(
            "UPDATE jobs SET model=?, variant=?, resolved=? WHERE id=?",
            (spec.id, variant.id, json.dumps(resolved, ensure_ascii=False), job.id),
        )
        updated = self.get(job.id)
        if updated:
            self.bus.publish("job", {"job": updated.to_api()})
        return params.model_copy(update=update), spec, variant, resolved

    def input_path(self, input_id: str) -> Path | None:
        """Disk path of a gallery image or an upload usable as an input picture."""
        row = self.db.one("SELECT path FROM images WHERE id=? AND deleted_at IS NULL", (input_id,))
        if row:
            return storage.resolve(self.settings.images_dir, row["path"])
        row = self.db.one("SELECT path FROM uploads WHERE id=?", (input_id,))
        if row:
            return storage.resolve(self.settings.uploads_dir, row["path"])
        return None

    async def _send_inputs(self, client: Any, params: GenerateParams) -> pipelines.BuildInputs:
        """Copy input pictures into the engine; returns their engine file names."""

        async def send(input_id: str) -> str:
            path = self.input_path(input_id)
            if path is None:
                raise EngineError("A reference picture no longer exists.")
            data = await asyncio.to_thread(path.read_bytes)
            name: str = await client.upload_image(f"photo-{input_id}.png", data)
            return name

        refs = tuple([await send(i) for i in params.references])
        source = await send(params.variation_of) if params.variation_of else None
        return pipelines.BuildInputs(references=refs, variation_source=source)

    def _writer_file(self) -> str | None:
        """An installed Qwen3 text encoder the language model can run from."""
        for spec in self.catalog.models:
            for f in spec.files.values():
                if (
                    f.dir == "text_encoders"
                    and f.name.startswith("qwen_3_4b")
                    and is_installed(self.settings.models, f)
                ):
                    return f.name
        return None

    async def enhance(self, prompt: str, style: Style | None, has_references: bool) -> str:
        """Rewrite a prompt with the local language model (no image is made)."""
        name = self._writer_file()
        if name is None:
            raise JobRejected("enhancer_unavailable", "Download a model first.")
        if self.engine.state is EngineState.NOT_INSTALLED:
            raise JobRejected("engine_not_installed", self.engine.last_error or "Engine missing.")
        try:
            client = await self.engine.wait_ready(timeout_s=120)
        except TimeoutError:
            raise JobRejected("engine_unavailable", "The engine is not ready.") from None
        built = pipelines.build_enhance(
            name, prompt, style, secrets.randbelow(MAX_SEED + 1), has_references
        )
        try:
            result = await client.run(built.graph.to_api(), built.output_node)
        except (EngineError, EngineUnavailable) as exc:
            code, message = friendly_error(exc)
            raise JobRejected(code, message) from exc
        text = result.texts.get(built.output_node, "").strip().strip('"')
        if not text:
            raise JobRejected("engine_error", "The language model returned nothing.")
        return text

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

    def _finish(
        self,
        job_id: str,
        status: JobStatus,
        error: str | None,
        error_code: str | None = None,
    ) -> None:
        self.db.execute(
            "UPDATE jobs SET status=?, error=?, error_code=?, finished_at=?, "
            "progress=CASE WHEN ?='succeeded' THEN 1 ELSE progress END WHERE id=?",
            (status, error, error_code, time.time(), status, job_id),
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
                code, message = friendly_error(exc)
                self._finish(job.id, "failed", message, code)

    async def _run(self, job: Job) -> None:
        if self.engine.state is EngineState.NOT_INSTALLED:
            self._finish(job.id, "failed", self.engine.last_error, "engine_not_installed")
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

        request = GenerateParams.model_validate(job.params)
        params = request
        spec = self.catalog.get(job.model)
        variant = spec.variant(job.variant)
        resolved: dict[str, Any] | None = None

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
            if request.style == AUTO or request.model == AUTO:
                params, spec, variant, resolved = await self._resolve_auto(client, job, request)
            inputs = await self._send_inputs(client, params)
            built = pipelines.build(
                params, spec, spec.variant_files(variant), job.seed, f"photo/{job.id}", inputs
            )
            result = await client.run(
                built.graph.to_api(),
                built.output_node,
                on_progress=on_progress,
                on_preview=on_preview,
            )
            if not result.images:
                raise EngineError("The engine finished without producing an image.")
            blobs = [await client.fetch_image(img) for img in result.images]
            if built.prompt_node:
                final_prompt = result.texts.get(built.prompt_node)
            elif resolved is not None:
                final_prompt = apply_style(params.prompt, get_style(params.style))
            else:
                final_prompt = None
            await self._store_outputs(
                job, spec, variant, params, blobs, final_prompt, request=request, resolved=resolved
            )
        except EngineInterrupted:
            self._finish(job.id, "cancelled", None)
            return
        except (EngineError, EngineUnavailable) as exc:
            if job.id in self._cancel_requested:
                self._finish(job.id, "cancelled", None)
            else:
                details = getattr(exc, "details", "")
                log.error("job %s failed: %s\n%s", job.id, exc, details)
                code, message = friendly_error(exc)
                self._finish(job.id, "failed", message, code)
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
        final_prompt: str | None = None,
        *,
        request: GenerateParams | None = None,
        resolved: dict[str, Any] | None = None,
    ) -> None:
        d = spec.defaults
        for index, raw in enumerate(blobs):
            image_id = new_id()
            meta = {
                "schema": 1,
                # The request as made: "auto" stays "auto", so reusing it decides afresh.
                "params": (request or params).model_dump(),
                "seed": job.seed,
                "batch_index": index,
                "steps": params.steps or d.steps,
                "cfg": params.cfg if params.cfg is not None else d.cfg,
                "model_variant": variant.id,
                # What the image model actually received, when the language model rewrote it.
                "final_prompt": final_prompt,
                "resolved": resolved,
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
