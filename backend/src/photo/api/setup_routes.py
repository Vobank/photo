"""Routes served while the setup wizard runs (``photo setup --ui``)."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from photo import __version__
from photo.installer import InstallConfig

if TYPE_CHECKING:
    from photo.api.app import SetupContext

router = APIRouter()


def _ctx(request: Request) -> SetupContext:
    ctx: SetupContext = request.app.state.setup
    return ctx


@router.get("/system")
async def system(request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    return {"mode": "setup", "version": __version__, "language": ctx.runner.base.language}


@router.get("/setup")
async def get_plan(request: Request) -> dict[str, Any]:
    return _ctx(request).runner.plan()


@router.post("/setup/validate")
async def validate(cfg: InstallConfig, request: Request) -> dict[str, Any]:
    errors = _ctx(request).runner.validate(cfg)
    return {"ok": not errors, "errors": [e.to_api() for e in errors]}


@router.post("/setup/start", status_code=202)
async def start(cfg: InstallConfig, request: Request) -> dict[str, Any]:
    runner = _ctx(request).runner
    if runner.state.status == "running":
        raise HTTPException(409, {"code": "already_running", "message": "Setup is already running"})
    errors = runner.validate(cfg)
    if errors:
        raise HTTPException(
            422,
            {
                "code": "invalid_config",
                "message": "Invalid setup choices",
                "fields": [e.to_api() for e in errors],
            },
        )
    return runner.start(cfg).to_api()


@router.post("/setup/cancel")
async def cancel(request: Request) -> dict[str, Any]:
    runner = _ctx(request).runner
    await runner.cancel()
    return runner.state.to_api()


@router.post("/setup/finish", status_code=202)
async def finish(request: Request) -> dict[str, str]:
    """Close the wizard; the installer then launches Photo on the same address."""
    ctx = _ctx(request)
    if ctx.runner.state.status != "done":
        raise HTTPException(409, {"code": "not_done", "message": "Setup has not finished"})
    asyncio.get_running_loop().call_later(0.3, ctx.request_exit)
    return {"status": "closing"}


@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    ctx: SetupContext = ws.app.state.setup
    await ws.accept()
    async with ctx.bus.subscribe() as queue:
        await ws.send_text(
            json.dumps({"type": "hello", "mode": "setup", "run": ctx.runner.state.to_api()})
        )

        async def pump() -> None:
            while True:
                frame = await queue.get()
                if frame.text is not None:
                    await ws.send_text(frame.text)

        sender = asyncio.create_task(pump())
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender
