"""The setup wizard's engine: plan, validate and run an installation.

The browser-based wizard (and nothing else) drives this. Every state change is
published on the event bus as a ``setup`` event so the UI can render progress.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from photo import prefs
from photo import setup as steps
from photo.catalog import Catalog, ModelFile, is_installed
from photo.config import LANGUAGES, Settings, config_file
from photo.disks import Disk, disk_for, free_space, list_disks
from photo.downloads import DownloadError, DownloadRequest, download
from photo.events import EventBus
from photo.hardware import MIN_DRIVER_MAJOR, Gpu

log = logging.getLogger(__name__)

# Measured size of a fresh engine environment (torch + CUDA libraries + ComfyUI deps).
ENGINE_ENV_BYTES = 6_500_000_000
# Space we insist stays free on any drive after installing, so the OS keeps working.
SAFETY_MARGIN = 2_000_000_000
# Suggested minimum room for the gallery.
DATA_HINT_BYTES = 5_000_000_000

StepId = Literal["engine", "packages", "gpu", "models"]
StepStatus = Literal["pending", "running", "done", "failed", "skipped"]
STEP_IDS: tuple[StepId, ...] = ("engine", "packages", "gpu", "models")


class InstallConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    language: str = Field(pattern=r"^[a-zA-Z-]{2,8}$")
    models_dir: str = Field(min_length=1, max_length=400)
    data_dir: str = Field(min_length=1, max_length=400)
    engine_env_dir: str = Field(min_length=1, max_length=400)
    models: list[str] = Field(default_factory=list, max_length=50)


@dataclass
class Step:
    id: StepId
    status: StepStatus = "pending"
    done: int = 0
    total: int = 0
    detail: str = ""

    def to_api(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "done": self.done,
            "total": self.total,
            "detail": self.detail,
        }


@dataclass
class RunState:
    status: Literal["idle", "running", "failed", "done"] = "idle"
    steps: list[Step] = field(default_factory=lambda: [Step(i) for i in STEP_IDS])
    error: dict[str, str] | None = None
    run_id: str = ""

    def step(self, step_id: StepId) -> Step:
        return next(s for s in self.steps if s.id == step_id)

    def to_api(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "steps": [s.to_api() for s in self.steps],
            "error": self.error,
            "run_id": self.run_id,
        }


@dataclass(frozen=True, slots=True)
class FieldError:
    field: str
    code: str
    detail: str = ""

    def to_api(self) -> dict[str, str]:
        return {"field": self.field, "code": self.code, "detail": self.detail}


def _forbidden_root(path: Path) -> bool:
    """System folders we must never write models or environments into."""
    s = str(path).lower().replace("/", "\\") if os.name == "nt" else str(path)
    if os.name == "nt":
        windir = os.environ.get("WINDIR", r"C:\Windows").lower()
        bad = [windir, r"c:\program files", r"c:\program files (x86)", r"c:\programdata"]
        return any(s == b or s.startswith(b + "\\") for b in bad)
    return any(
        s == b or s.startswith(b + "/")
        for b in ("/bin", "/boot", "/dev", "/etc", "/proc", "/sys", "/usr", "/var/lib")
    )


def _probe_writable(path: Path) -> bool:
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            return False
        probe = probe.parent
    try:
        with tempfile.NamedTemporaryFile(dir=probe, prefix=".photo-write-test-"):
            pass
    except OSError:
        return False
    return True


class SetupRunner:
    def __init__(self, settings: Settings, catalog: Catalog, bus: EventBus, gpu: Gpu | None):
        self.base = settings
        self.catalog = catalog
        self.bus = bus
        self.gpu = gpu
        self.state = RunState()
        self._task: asyncio.Task[None] | None = None
        self._last_emit = 0.0

    # ---- planning ------------------------------------------------------------------

    def _engine_env_ready(self, s: Settings) -> bool:
        return s.engine_python.exists()

    def _model_files(self, model_ids: list[str]) -> list[ModelFile]:
        files: dict[str, ModelFile] = {}
        for model_id in model_ids:
            spec = self.catalog.get(model_id)
            for f in spec.variant_files(spec.choose_variant(self.gpu)).values():
                files[f.name] = f
        return list(files.values())

    def plan(self) -> dict[str, Any]:
        s = self.base
        gpu = self.gpu
        disks = list_disks()
        models = []
        for spec in self.catalog.models:
            variant = spec.choose_variant(gpu)
            files = spec.variant_files(variant).values()
            models.append({
                "id": spec.id,
                "name": spec.name,
                "vendor": spec.vendor,
                "license": spec.license,
                "license_url": spec.license_url,
                "commercial_use": spec.commercial_use,
                "variant": variant.label,
                "bytes": sum(f.size for f in files),
                "installed": all(is_installed(s.models, f) for f in files),
                "recommended": spec is self.catalog.models[0],
            })  # fmt: skip
        return {
            "languages": list(LANGUAGES),
            "defaults": {
                "language": s.language,
                "models_dir": str(s.models),
                "data_dir": str(s.data),
                "engine_env_dir": str(s.engine_env),
            },
            "configured": config_file().exists(),
            "install_dir": str(s.home),
            "engine_env_bytes": 0 if self._engine_env_ready(s) else ENGINE_ENV_BYTES,
            "data_hint_bytes": DATA_HINT_BYTES,
            "disks": [d.to_api() for d in disks],
            "gpu": None
            if gpu is None
            else {
                "name": gpu.name,
                "vram_gb": gpu.vram_gb,
                "arch": gpu.arch,
                "driver": gpu.driver,
                "supported": gpu.supported,
                "driver_ok": gpu.driver_major >= MIN_DRIVER_MAJOR,
            },
            "min_driver": MIN_DRIVER_MAJOR,
            "models": models,
            "run": self.state.to_api(),
        }

    def validate(self, cfg: InstallConfig) -> list[FieldError]:
        errors: list[FieldError] = []
        if cfg.language not in LANGUAGES:
            errors.append(FieldError("language", "unsupported_language"))
        for model_id in cfg.models:
            try:
                self.catalog.get(model_id)
            except KeyError:
                errors.append(FieldError("models", "unknown_model", model_id))

        paths: dict[str, Path] = {}
        for name in ("models_dir", "data_dir", "engine_env_dir"):
            raw = Path(getattr(cfg, name)).expanduser()
            if not raw.is_absolute():
                errors.append(FieldError(name, "path_not_absolute"))
                continue
            path = raw.resolve()
            if _forbidden_root(path):
                errors.append(FieldError(name, "path_system_folder", str(path)))
            elif path.exists() and not path.is_dir():
                errors.append(FieldError(name, "path_is_file", str(path)))
            elif not _probe_writable(path):
                errors.append(FieldError(name, "path_not_writable", str(path)))
            else:
                paths[name] = path
        if errors:
            return errors

        # Space needed per drive, after accounting for what is already in place.
        disks = list_disks()
        need: dict[str, int] = {}
        owners: dict[str, list[str]] = {}

        def add(field_name: str, path: Path, size: int) -> None:
            d: Disk | None = disk_for(path, disks)
            key = d.root if d else str(path.anchor or path)
            need[key] = need.get(key, 0) + size
            owners.setdefault(key, []).append(field_name)

        env_dir = paths["engine_env_dir"]
        env_python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        add("engine_env_dir", env_dir, 0 if env_python.exists() else ENGINE_ENV_BYTES)
        models_dir = paths["models_dir"]
        add(
            "models_dir",
            models_dir,
            sum(f.size for f in self._model_files(cfg.models) if not is_installed(models_dir, f)),
        )
        add("data_dir", paths["data_dir"], 0)

        for key, bytes_needed in need.items():
            if not bytes_needed:
                continue
            probe = next(p for n, p in paths.items() if n in owners[key])
            free = free_space(probe)
            if free < bytes_needed + SAFETY_MARGIN:
                for f in owners[key]:
                    errors.append(
                        FieldError(f, "not_enough_space", f"{bytes_needed + SAFETY_MARGIN}:{free}")
                    )
        return errors

    # ---- running -------------------------------------------------------------------

    def _emit(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_emit >= 0.25:
            self._last_emit = now
            self.bus.publish("setup", {"run": self.state.to_api()})

    def start(self, cfg: InstallConfig) -> RunState:
        if self._task and not self._task.done():
            return self.state
        self.state = RunState(status="running", run_id=uuid.uuid4().hex)
        self._task = asyncio.create_task(self._run(cfg), name="setup")
        self._emit(force=True)
        return self.state

    async def cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self, cfg: InstallConfig) -> None:
        current: Step | None = None
        try:
            old = self.base
            prefs.update({
                "language": cfg.language,
                "models_dir": cfg.models_dir,
                "data_dir": cfg.data_dir,
                "engine_env_dir": cfg.engine_env_dir,
            })  # fmt: skip
            s = Settings(
                home=old.home,
                language=cfg.language,
                models_dir=Path(cfg.models_dir),
                data_dir=Path(cfg.data_dir),
                engine_env_dir=Path(cfg.engine_env_dir),
                runtime_dir=old.runtime,
                hf_endpoint=old.hf_endpoint,
                hf_token=old.hf_token,
            )
            s.ensure_dirs()

            current = self.state.step("engine")
            await self._step_engine(s, current)
            current = self.state.step("packages")
            await self._step_packages(s, current)
            current = self.state.step("gpu")
            await self._step_gpu(s, current)
            current = self.state.step("models")
            await self._step_models(s, old, cfg.models, current)
            current = None

            self._cleanup_old_env(old, s)
            self.base = s
            self.state.status = "done"
        except asyncio.CancelledError:
            self.state.status = "failed"
            self.state.error = {
                "code": "cancelled",
                "detail": "",
                "step": current.id if current else "",
            }
            if current:
                current.status = "failed"
            self._emit(force=True)
            raise
        except steps.SetupError as exc:
            self._fail(current, exc.code, str(exc))
        except DownloadError as exc:
            self._fail(current, "download_failed", str(exc))
        except OSError as exc:
            self._fail(current, "disk_error", str(exc))
        except Exception as exc:
            log.exception("setup crashed")
            self._fail(current, "setup_failed", f"{type(exc).__name__}: {exc}")
        self._emit(force=True)

    def _fail(self, step: Step | None, code: str, detail: str) -> None:
        log.error("setup failed at %s: %s %s", step.id if step else "-", code, detail)
        self.state.status = "failed"
        self.state.error = {"code": code, "detail": detail, "step": step.id if step else ""}
        if step:
            step.status = "failed"

    async def _step_engine(self, s: Settings, step: Step) -> None:
        pin = steps.engine_pin(s)
        if steps.installed_engine_commit(s) == pin.commit:
            step.status = "skipped"
            self._emit(force=True)
            return
        step.status = "running"
        step.total = pin.size
        self._emit(force=True)
        s.runtime.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=s.runtime) as tmp:
            archive = Path(tmp) / "engine.tar.gz"

            def progress(done: int, _total: int) -> None:
                step.done = done
                self._emit()

            await download(DownloadRequest(pin.url, archive, pin.size, pin.sha256), progress)
            await asyncio.to_thread(steps.install_engine_source, s, archive)
        step.status = "done"
        self._emit(force=True)

    async def _step_packages(self, s: Settings, step: Step) -> None:
        step.status = "running"
        self._emit(force=True)
        uv = steps.find_uv(s)

        def on_line(line: str) -> None:
            step.detail = line[:200]
            self._emit()

        await steps.sync_engine_env_streaming(s, uv, on_line)
        step.detail = ""
        step.status = "done"
        self._emit(force=True)

    async def _step_gpu(self, s: Settings, step: Step) -> None:
        step.status = "running"
        self._emit(force=True)
        step.detail = await asyncio.to_thread(steps.verify_engine_cuda, s)
        step.status = "done"
        self._emit(force=True)

    async def _step_models(
        self, s: Settings, old: Settings, model_ids: list[str], step: Step
    ) -> None:
        files = [f for f in self._model_files(model_ids) if not is_installed(s.models, f)]
        if not files:
            step.status = "skipped"
            self._emit(force=True)
            return
        step.status = "running"
        step.total = sum(f.size for f in files)
        self._emit(force=True)

        base = 0
        for f in files:
            dest = s.models / f.relative_path
            previous = old.models / f.relative_path
            if previous != dest and is_installed(old.models, f):
                # The user picked a new drive: move what we already have instead of downloading.
                step.detail = f.name
                self._emit(force=True)
                dest.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.move, previous, dest)
            else:
                step.detail = f.name

                def progress(done: int, _total: int, offset: int = base) -> None:
                    step.done = offset + done
                    self._emit()

                await download(
                    DownloadRequest(f.url(s.hf_endpoint), dest, f.size, f.sha256, s.hf_token),
                    progress,
                )
            base += f.size
            step.done = base
        step.detail = ""
        step.status = "done"
        self._emit(force=True)

    def _cleanup_old_env(self, old: Settings, new: Settings) -> None:
        """Free the space of an engine environment the user moved to another drive."""
        if old.engine_env == new.engine_env or not old.engine_env.exists():
            return
        # Only ever delete the environment we created inside the install folder.
        if old.engine_env == (old.home / "engine" / ".venv").resolve():
            shutil.rmtree(old.engine_env, ignore_errors=True)
