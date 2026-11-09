from __future__ import annotations

import asyncio
import io
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from photo.api.app import Services, build_services, create_app
from photo.catalog import Catalog, default_catalog
from photo.config import Settings
from photo.engine.client import OutputImage, Preview, Progress, RunResult
from photo.engine.process import EngineState
from photo.hardware import Gpu

RTX_5080 = Gpu(0, "NVIDIA GeForce RTX 5080", 16303, "617.42", "12.0")
RTX_4060 = Gpu(0, "NVIDIA GeForce RTX 4060", 8188, "581.15", "8.9")


def png_bytes(w: int = 64, h: int = 48, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(self) -> None:
        self.graphs: list[dict[str, Any]] = []
        self.block: asyncio.Event | None = None
        self.interrupted = False
        self.fail_with: Exception | None = None
        self.uploads: dict[str, bytes] = {}
        # What the language model answers to automatic mode's classification step.
        self.classify_answer = "photo | a lighthouse at dusk"

    async def run(
        self, graph: dict[str, Any], output_node: str, *, on_progress=None, on_preview=None
    ) -> RunResult:
        self.graphs.append(graph)
        if on_progress:
            await on_progress(Progress(1, 2))
        if on_preview:
            await on_preview(Preview("image/jpeg", b"\xff\xd8preview"))
        if self.block is not None:
            await self.block.wait()
        if self.interrupted:
            from photo.engine.client import EngineInterrupted

            raise EngineInterrupted()
        if self.fail_with:
            raise self.fail_with
        if on_progress:
            await on_progress(Progress(2, 2))
        batch = graph_batch(graph)
        from photo.auto import CLASSIFY_SYSTEM

        classify = any(n["inputs"].get("system_prompt") == CLASSIFY_SYSTEM for n in graph.values())
        answer = self.classify_answer if classify else "Enhanced: a vivid scene"
        texts = {
            node_id: answer for node_id, node in graph.items() if node["class_type"] == "PreviewAny"
        }
        images = [OutputImage(f"out_{i}.png", "photo", "output") for i in range(batch)]
        if any(n["class_type"] == "SaveImage" for n in graph.values()):
            return RunResult(images, texts)
        return RunResult([], texts)

    async def upload_image(self, name: str, data: bytes) -> str:
        self.uploads[name] = data
        return name

    async def fetch_image(self, img: OutputImage) -> bytes:
        return png_bytes()

    async def interrupt(self) -> None:
        self.interrupted = True
        if self.block:
            self.block.set()


def graph_batch(graph: dict[str, Any]) -> int:
    for node in graph.values():
        if node["class_type"] in ("EmptySD3LatentImage", "EmptyFlux2LatentImage"):
            return int(node["inputs"]["batch_size"])
        if node["class_type"] == "RepeatLatentBatch":
            return int(node["inputs"]["amount"])
    return 1


class FakeEngine:
    def __init__(self) -> None:
        self.client = FakeClient()
        self.state = EngineState.READY
        self.last_error: str | None = None
        self.on_state_change = None

    async def start(self) -> None:
        self.state = EngineState.READY

    async def stop(self) -> None:
        self.state = EngineState.STOPPED

    async def restart(self) -> None:
        pass

    async def wait_ready(self, timeout_s: float | None = None) -> FakeClient:
        return self.client


@pytest.fixture(autouse=True)
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never read or write the developer's real photo.toml from tests."""
    path = tmp_path / "photo.toml"
    monkeypatch.setenv("PHOTO_CONFIG", str(path))
    for var in ("PHOTO_LANGUAGE", "PHOTO_MODELS_DIR", "PHOTO_DATA_DIR", "PHOTO_ENGINE_ENV_DIR"):
        monkeypatch.delenv(var, raising=False)
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(home=tmp_path, hf_endpoint="https://hf.test")


TINY_SIZE = 16


def tiny_catalog() -> Catalog:
    """The real catalog with every file shrunk to 16 bytes, so tests can 'install' models."""
    raw = default_catalog().model_dump(by_alias=True)
    for m in raw["models"]:
        for f in m["files"].values():
            f["size"] = TINY_SIZE
    return Catalog.model_validate(raw)


def install_fake_model(
    services: Services, model_id: str = "z-image-turbo", variant: str = "nvfp4"
) -> None:
    spec = services.catalog.get(model_id)
    for f in spec.variant_files(spec.variant(variant)).values():
        p = services.settings.models / f.relative_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(bytes(f.size))


@pytest.fixture
def services(settings: Settings) -> Services:
    return build_services(
        settings,
        gpus=[RTX_5080],
        engine=FakeEngine(),
        catalog=tiny_catalog(),  # type: ignore[arg-type]
    )  # type: ignore[arg-type]


@pytest.fixture
def client(services: Services) -> Iterator[TestClient]:
    app = create_app(services, start_engine=False)
    with TestClient(app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 50000)) as c:
        yield c
