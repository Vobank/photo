"""In-process pub/sub that fans job events out to connected browsers.

State events are never dropped. Step previews are best-effort: a slow client simply
misses some frames instead of slowing the GPU worker down.
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

_QUEUE_SIZE = 512


@dataclass(frozen=True, slots=True)
class Frame:
    """One WebSocket message: text (JSON) or binary (preview)."""

    text: str | None = None
    data: bytes | None = None


def encode_preview(job_id: str, mime: str, image: bytes) -> bytes:
    """Binary layout: uint32 BE header length · UTF-8 JSON header · image bytes."""
    header = json.dumps({"type": "preview", "job_id": job_id, "mime": mime}).encode()
    return struct.pack(">I", len(header)) + header + image


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Frame]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        frame = Frame(text=json.dumps({"type": event_type, **payload}, ensure_ascii=False))
        for q in self._subscribers:
            while True:
                try:
                    q.put_nowait(frame)
                    break
                except asyncio.QueueFull:
                    q.get_nowait()  # drop the oldest frame, keep the newest state

    def publish_preview(self, job_id: str, mime: str, image: bytes) -> None:
        frame = Frame(data=encode_preview(job_id, mime, image))
        for q in self._subscribers:
            if q.qsize() < _QUEUE_SIZE // 2:
                q.put_nowait(frame)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Frame]]:
        q: asyncio.Queue[Frame] = asyncio.Queue(_QUEUE_SIZE)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)
