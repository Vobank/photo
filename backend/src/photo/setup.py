"""Installation steps shared by the installer (`photo setup`) and the doctor."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import subprocess
import tarfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from photo.config import Settings
from photo.hardware import MIN_DRIVER_MAJOR, Arch, Gpu


class SetupError(Exception):
    """A step failed. ``code`` lets the UI explain it in the user's language;
    ``str(exc)`` is the English technical detail."""

    def __init__(self, message: str, code: str = "setup_failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class EnginePin:
    version: str
    commit: str
    url: str
    sha256: str
    size: int


def engine_pin(settings: Settings) -> EnginePin:
    with (settings.home / "engine" / "engine.toml").open("rb") as fh:
        d = tomllib.load(fh)
    return EnginePin(d["version"], d["commit"], d["url"], d["sha256"], d["size"])


def installed_engine_commit(settings: Settings) -> str | None:
    marker = settings.engine_source_dir / ".photo-commit"
    try:
        return marker.read_text().strip()
    except OSError:
        return None


# ---- checks ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def check_gpu(gpu: Gpu | None) -> list[Check]:
    if gpu is None:
        return [Check(
            "NVIDIA GPU", False,
            "No NVIDIA GPU found (nvidia-smi missing or failing). Install the latest NVIDIA "
            "driver from nvidia.com/drivers.",
        )]  # fmt: skip
    checks = [
        Check(
            "NVIDIA GPU",
            gpu.supported,
            f"{gpu.name}, {gpu.vram_gb} GB"
            + (
                ""
                if gpu.supported
                else " — RTX 40/50 series recommended; this card may be slow or fail."
            ),
            fatal=gpu.arch in (Arch.OLDER, Arch.UNKNOWN),
        ),
        Check(
            "NVIDIA driver",
            gpu.driver_major >= MIN_DRIVER_MAJOR,
            f"{gpu.driver}"
            + (
                ""
                if gpu.driver_major >= MIN_DRIVER_MAJOR
                else f" — version {MIN_DRIVER_MAJOR}+ required. Update at nvidia.com/drivers."
            ),
        ),
    ]
    return checks


def check_disk(settings: Settings, needed_gb: float) -> Check:
    probe = settings.models
    while not probe.exists():
        probe = probe.parent
    free_gb = shutil.disk_usage(probe).free / 2**30
    return Check(
        "Disk space",
        free_gb >= needed_gb,
        f"{free_gb:.0f} GB free on {probe.anchor or probe} (need about {needed_gb:.0f} GB)",
    )


# ---- engine install ----------------------------------------------------------------


def find_uv(settings: Settings) -> str:
    env = os.environ.get("PHOTO_UV")
    candidates = [env] if env else []
    exe = "uv.exe" if os.name == "nt" else "uv"
    candidates += [str(settings.runtime / "bin" / exe), shutil.which("uv") or ""]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise SetupError(
        "uv not found. Run the installer (install.ps1 / install.sh) instead.", "uv_missing"
    )


def _safe_extract(archive: Path, dest: Path) -> None:
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(dest, filter="data")  # rejects absolute paths, links out, devices


def install_engine_source(settings: Settings, archive: Path) -> None:
    """Verify ``archive`` against the pin and unpack it into runtime/comfyui."""
    pin = engine_pin(settings)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != pin.sha256:
        raise SetupError(
            f"Engine archive checksum mismatch (expected {pin.sha256[:12]}…, got {digest[:12]}…). "
            "The download was corrupted or tampered with; try again.",
            "engine_checksum",
        )
    staging = settings.runtime / "comfyui.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    _safe_extract(archive, staging)
    roots = [p for p in staging.iterdir() if p.is_dir()]
    if len(roots) != 1 or not (roots[0] / "main.py").exists():
        raise SetupError("Engine archive has an unexpected layout.", "engine_checksum")
    (roots[0] / ".photo-commit").write_text(pin.commit)

    target = settings.engine_source_dir
    old = settings.runtime / "comfyui.old"
    shutil.rmtree(old, ignore_errors=True)
    if target.exists():
        target.rename(old)
    roots[0].rename(target)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)


def _engine_sync_cmd(settings: Settings, uv: str) -> tuple[list[str], dict[str, str]]:
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(settings.engine_env)}
    env.pop("VIRTUAL_ENV", None)
    cmd = [uv, "sync", "--locked", "--no-dev", "--project", str(settings.home / "engine")]
    return cmd, env


def sync_engine_env(settings: Settings, uv: str) -> None:
    cmd, env = _engine_sync_cmd(settings, uv)
    proc = subprocess.run(cmd, env=env, check=False)  # noqa: S603 — fixed argv
    if proc.returncode != 0:
        raise SetupError("Installing engine packages failed (see output above).", "engine_packages")


async def sync_engine_env_streaming(
    settings: Settings, uv: str, on_line: Callable[[str], None]
) -> None:
    """Same as :func:`sync_engine_env`, reporting each output line (for the wizard)."""
    cmd, env = _engine_sync_cmd(settings, uv)
    env["NO_COLOR"] = "1"
    proc = await asyncio.create_subprocess_exec(
        *cmd, env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    assert proc.stdout is not None
    tail: list[str] = []
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "replace").strip()
        if line:
            tail = [*tail[-19:], line]
            on_line(line)
    if await proc.wait() != 0:
        raise SetupError(
            "Installing engine packages failed:\n" + "\n".join(tail[-8:]), "engine_packages"
        )


def verify_engine_cuda(settings: Settings) -> str:
    """Run a tiny CUDA op in the engine env. Returns a description of the device."""
    code = (
        "import torch;"
        "assert torch.cuda.is_available(), 'CUDA not available';"
        "x=torch.ones(64,64,device='cuda');(x@x).sum().item();"
        "p=torch.cuda.get_device_properties(0);"
        "print(f'torch {torch.__version__}, CUDA {torch.version.cuda}, "
        "{p.name}, sm_{p.major}{p.minor}')"
    )
    proc = subprocess.run(  # noqa: S603
        [str(settings.engine_python), "-s", "-c", code],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
        raise SetupError("The engine cannot use the GPU: " + " | ".join(tail), "cuda_unavailable")
    return proc.stdout.strip()


# ---- frontend ----------------------------------------------------------------------


def ensure_frontend(settings: Settings) -> str:
    if (settings.frontend_dist / "index.html").exists():
        return "prebuilt"
    npm = shutil.which("npm")
    if npm is None:
        raise SetupError(
            "The web UI is not built and Node.js is not installed. Download a release "
            "package from GitHub (it includes the built UI) or install Node.js 22+.",
            "frontend_missing",
        )
    front = settings.home / "frontend"
    for args in (["ci", "--no-audit", "--no-fund"], ["run", "build"]):
        proc = subprocess.run([npm, *args], cwd=front, check=False)  # noqa: S603
        if proc.returncode != 0:
            raise SetupError(
                f"`npm {' '.join(args)}` failed (see output above).", "frontend_missing"
            )
    return "built"
