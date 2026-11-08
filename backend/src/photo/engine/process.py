"""Supervises the engine subprocess: start, health, crash restart, shutdown."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from enum import StrEnum
from pathlib import Path

from photo.config import Settings
from photo.engine.client import EngineClient, wait_until_ready
from photo.hardware import Gpu

log = logging.getLogger(__name__)

_BOOT = Path(__file__).with_name("boot.py")
_MAX_RESTARTS = 3
_RESTART_WINDOW_S = 600


class EngineState(StrEnum):
    NOT_INSTALLED = "not_installed"
    STOPPED = "stopped"
    STARTING = "starting"
    READY = "ready"
    CRASHED = "crashed"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def build_command(settings: Settings, port: int, gpu: Gpu | None) -> list[str]:
    state = settings.engine_state_dir
    cmd = [
        str(settings.engine_python),
        "-s",  # ignore user site-packages: they break reproducibility
        str(_BOOT),
        "--parent-pid",
        str(os.getpid()),
        "--comfy-dir",
        str(settings.engine_source_dir),
        "--",
        "--listen", "127.0.0.1",
        "--port", str(port),
        "--disable-auto-launch",
        "--disable-api-nodes",
        "--disable-manager-ui",
        "--disable-product-tips",
        "--preview-method", "auto",
        "--models-directory", str(settings.models),
        "--output-directory", str(state / "output"),
        "--input-directory", str(state / "input"),
        "--temp-directory", str(state / "temp"),
        "--user-directory", str(state / "user"),
        "--database-url", f"sqlite:///{(state / 'engine.db').as_posix()}",
    ]  # fmt: skip
    if gpu is not None:
        cmd += ["--cuda-device", str(gpu.index)]
    cmd += list(settings.engine_extra_args)
    return cmd


class EngineProcess:
    def __init__(self, settings: Settings, gpu: Gpu | None) -> None:
        self.settings = settings
        self.gpu = gpu
        self.on_state_change: Callable[[EngineState, str | None], None] | None = None
        self._state = EngineState.STOPPED
        self.last_error: str | None = None
        self.client: EngineClient | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._restarts: list[float] = []
        self._stopping = False
        self._ready = asyncio.Event()

    @property
    def state(self) -> EngineState:
        return self._state

    @state.setter
    def state(self, value: EngineState) -> None:
        self._state = value
        if self.on_state_change:
            self.on_state_change(value, self.last_error)

    @property
    def installed(self) -> bool:
        s = self.settings
        return s.engine_python.exists() and (s.engine_source_dir / "main.py").exists()

    async def wait_ready(self, timeout_s: float | None = None) -> EngineClient:
        await asyncio.wait_for(self._ready.wait(), timeout_s)
        assert self.client is not None
        return self.client

    async def start(self) -> None:
        if not self.installed:
            self.last_error = "Engine is not installed. Run the installer again."
            self.state = EngineState.NOT_INSTALLED
            log.error(self.last_error)
            return
        self._stopping = False
        await self._spawn()
        self._monitor = asyncio.create_task(self._watch(), name="engine-monitor")

    async def _spawn(self) -> None:
        self.state = EngineState.STARTING
        self._ready.clear()
        port = self.settings.engine_port or free_port()
        for sub in ("output", "input", "temp", "user"):
            (self.settings.engine_state_dir / sub).mkdir(parents=True, exist_ok=True)

        self.settings.logs_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.settings.logs_dir / "engine.log"
        if log_path.exists():
            os.replace(log_path, log_path.with_suffix(".prev.log"))
        log_file = log_path.open("wb")

        env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        env.pop("PYTHONPATH", None)
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW  # no console window flashing up
        cmd = build_command(self.settings, port, self.gpu)
        log.info("starting engine on port %d", port)
        # Popen only forks/spawns; it does not wait. argv comes from trusted settings.
        self._proc = subprocess.Popen(  # noqa: S603, ASYNC220
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
        )
        log_file.close()  # child holds its own handle

        if self.client:
            await self.client.aclose()
        self.client = EngineClient(f"http://127.0.0.1:{port}")
        try:
            await wait_until_ready(self.client, self.settings.engine_start_timeout_s)
        except Exception as exc:
            # Kill a hung engine so the monitor sees an exit and applies restart policy.
            if self._proc.poll() is None:
                self._proc.kill()
            self.last_error = f"{exc}. See {log_path}."
            self.state = EngineState.CRASHED
            log.error("engine failed to start: %s", exc)
            return
        self.last_error = None
        self.state = EngineState.READY
        self._ready.set()
        log.info("engine ready")

    async def _watch(self) -> None:
        while not self._stopping:
            await asyncio.sleep(1.0)
            proc = self._proc
            if proc is None or proc.poll() is None:
                continue
            if self._stopping:
                return
            code = proc.returncode
            self._ready.clear()
            self.last_error = f"Engine exited unexpectedly (code {code}). See logs/engine.log."
            self.state = EngineState.CRASHED
            log.error(self.last_error)

            now = time.monotonic()
            self._restarts = [t for t in self._restarts if now - t < _RESTART_WINDOW_S]
            if len(self._restarts) >= _MAX_RESTARTS:
                log.error(
                    "engine crashed %d times in %ds; not restarting",
                    _MAX_RESTARTS,
                    _RESTART_WINDOW_S,
                )
                return
            self._restarts.append(now)
            await asyncio.sleep(2 ** len(self._restarts))
            await self._spawn()

    async def restart(self) -> None:
        await self.stop()
        self._restarts.clear()
        await self.start()

    async def stop(self) -> None:
        self._stopping = True
        self._ready.clear()
        if self._monitor:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                await asyncio.to_thread(proc.wait, 15)
            except subprocess.TimeoutExpired:
                proc.kill()
                await asyncio.to_thread(proc.wait, 5)
        self._proc = None
        if self.client:
            await self.client.aclose()
            self.client = None
        if self.state is not EngineState.NOT_INSTALLED:
            self.state = EngineState.STOPPED
