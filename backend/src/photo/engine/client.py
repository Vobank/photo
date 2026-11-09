"""Async client for the engine's (ComfyUI) HTTP + WebSocket API."""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets

log = logging.getLogger(__name__)

# ComfyUI BinaryEventTypes
_PREVIEW_IMAGE = 1
_PREVIEW_IMAGE_WITH_METADATA = 4
_IMAGE_MIME = {1: "image/jpeg", 2: "image/png"}


class EngineError(Exception):
    """The engine rejected or failed a graph. ``message`` is safe to show to users."""

    def __init__(self, message: str, *, node_type: str | None = None, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.node_type = node_type
        self.details = details


class EngineInterrupted(Exception):
    pass


class EngineUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class OutputImage:
    filename: str
    subfolder: str
    type: str


@dataclass(frozen=True, slots=True)
class Progress:
    value: int
    max: int
    node: str | None = None


@dataclass(frozen=True, slots=True)
class Preview:
    mime: str
    data: bytes


@dataclass
class RunResult:
    images: list[OutputImage] = field(default_factory=list)
    # Text shown by preview nodes, by node id (e.g. the enhanced prompt).
    texts: dict[str, str] = field(default_factory=dict)


OnProgress = Callable[[Progress], Awaitable[None]]
OnPreview = Callable[[Preview], Awaitable[None]]


def parse_binary_frame(frame: bytes) -> tuple[Preview, str | None] | None:
    """Decode a preview frame. Returns (preview, prompt_id or None)."""
    if len(frame) < 8:
        return None
    (event,) = struct.unpack(">I", frame[:4])
    if event == _PREVIEW_IMAGE:
        (img_type,) = struct.unpack(">I", frame[4:8])
        return Preview(_IMAGE_MIME.get(img_type, "image/jpeg"), bytes(frame[8:])), None
    if event == _PREVIEW_IMAGE_WITH_METADATA:
        (meta_len,) = struct.unpack(">I", frame[4:8])
        meta_end = 8 + meta_len
        if meta_end > len(frame):
            return None
        try:
            meta = json.loads(frame[8:meta_end])
        except ValueError:
            return None
        mime = meta.get("image_type", "image/jpeg")
        return Preview(mime, bytes(frame[meta_end:])), meta.get("prompt_id")
    return None


def _format_node_errors(body: dict[str, Any]) -> str:
    err = body.get("error") or {}
    parts = [str(err.get("message") or "Graph rejected by engine")]
    for node_id, info in (body.get("node_errors") or {}).items():
        for e in info.get("errors", []):
            parts.append(
                f"{info.get('class_type', node_id)}: {e.get('message')} {e.get('details', '')}"
            )
    return "; ".join(p.strip() for p in parts if p)


class EngineClient:
    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout_s)

    @property
    def ws_url(self) -> str:
        return self.base_url.replace("http://", "ws://", 1).replace("https://", "wss://", 1) + "/ws"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def system_stats(self) -> dict[str, Any]:
        r = await self._http.get("/system_stats")
        r.raise_for_status()
        data: dict[str, Any] = r.json()
        return data

    async def is_ready(self) -> bool:
        try:
            await self.system_stats()
        except (httpx.HTTPError, ValueError):
            return False
        return True

    async def interrupt(self) -> None:
        try:
            await self._http.post("/interrupt", json={})
        except httpx.HTTPError as exc:
            log.warning("interrupt failed: %s", exc)

    async def free_memory(self) -> None:
        await self._http.post("/free", json={"unload_models": True, "free_memory": True})

    async def fetch_image(self, img: OutputImage) -> bytes:
        r = await self._http.get(
            "/view", params={"filename": img.filename, "subfolder": img.subfolder, "type": img.type}
        )
        r.raise_for_status()
        return r.content

    async def upload_image(self, name: str, data: bytes) -> str:
        r = await self._http.post(
            "/upload/image",
            files={"image": (name, data, "application/octet-stream")},
            data={"overwrite": "true", "type": "input"},
        )
        r.raise_for_status()
        body = r.json()
        sub = body.get("subfolder") or ""
        return f"{sub}/{body['name']}" if sub else str(body["name"])

    async def run(
        self,
        graph: dict[str, Any],
        output_node: str,
        *,
        on_progress: OnProgress | None = None,
        on_preview: OnPreview | None = None,
    ) -> RunResult:
        """Submit ``graph`` and wait for it to finish.

        The WebSocket is opened *before* submitting so no event can be missed.
        """
        client_id = uuid.uuid4().hex
        try:
            ws = await websockets.connect(
                f"{self.ws_url}?clientId={client_id}", max_size=64 * 2**20, open_timeout=15
            )
        except (OSError, websockets.InvalidHandshake, TimeoutError) as exc:
            raise EngineUnavailable(f"cannot connect to engine: {exc}") from exc

        async with ws:
            prompt_id = await self._submit(graph, client_id)
            result = RunResult()
            async for message in ws:
                if isinstance(message, bytes):
                    decoded = parse_binary_frame(message)
                    if decoded and on_preview:
                        preview, pid = decoded
                        if pid in (None, prompt_id):
                            await on_preview(preview)
                    continue

                msg = json.loads(message)
                mtype, data = msg.get("type"), msg.get("data") or {}
                if data.get("prompt_id") not in (None, prompt_id):
                    continue

                if mtype == "progress" and on_progress:
                    await on_progress(
                        Progress(int(data["value"]), int(data["max"]), data.get("node"))
                    )
                elif mtype == "executed" and (data.get("output") or {}).get("text"):
                    texts = data["output"]["text"]
                    result.texts[str(data.get("node"))] = "".join(str(t) for t in texts)
                elif mtype == "executed" and str(data.get("node")) == output_node:
                    for img in (data.get("output") or {}).get("images", []):
                        result.images.append(
                            OutputImage(
                                img["filename"], img.get("subfolder", ""), img.get("type", "output")
                            )
                        )
                elif mtype == "execution_success":
                    if not result.images:
                        # Fully cached runs may skip "executed"; history always has outputs.
                        result.images = await self._history_images(prompt_id, output_node)
                    return result
                elif mtype == "execution_error":
                    raise EngineError(
                        str(data.get("exception_message") or "Engine error").strip(),
                        node_type=data.get("node_type"),
                        details="".join(data.get("traceback") or []),
                    )
                elif mtype == "execution_interrupted":
                    raise EngineInterrupted()
                elif mtype == "executing" and data.get("node") is None and data.get("prompt_id"):
                    # Legacy completion signal on older engines.
                    return result

        raise EngineUnavailable("engine closed the connection mid-run")

    async def _history_images(self, prompt_id: str, output_node: str) -> list[OutputImage]:
        r = await self._http.get(f"/history/{prompt_id}")
        r.raise_for_status()
        entry = (r.json() or {}).get(prompt_id) or {}
        images = ((entry.get("outputs") or {}).get(output_node) or {}).get("images", [])
        return [
            OutputImage(i["filename"], i.get("subfolder", ""), i.get("type", "output"))
            for i in images
        ]

    async def _submit(self, graph: dict[str, Any], client_id: str) -> str:
        try:
            r = await self._http.post("/prompt", json={"prompt": graph, "client_id": client_id})
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"engine not reachable: {exc}") from exc
        if r.status_code == 400:
            raise EngineError(_format_node_errors(r.json()))
        r.raise_for_status()
        return str(r.json()["prompt_id"])


async def wait_until_ready(client: EngineClient, timeout_s: float, poll_s: float = 0.5) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        if await client.is_ready():
            return
        await asyncio.sleep(poll_s)
    raise EngineUnavailable(f"engine did not become ready within {timeout_s:.0f}s")
