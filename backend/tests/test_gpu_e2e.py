"""End-to-end test against the real engine and GPU.

Skipped unless run explicitly:  uv run pytest -m gpu -s
Requires an installed engine and the Z-Image Turbo model. Prints timings, which
are the source of the speed figures in the README.
"""

from __future__ import annotations

import io
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from PIL import Image

from photo import storage
from photo.catalog import default_catalog
from photo.config import Settings
from photo.hardware import detect_gpus, primary_gpu
from photo.jobs import installed_variant

pytestmark = pytest.mark.gpu

MODEL = "z-image-turbo"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    real = Settings()
    gpu = primary_gpu(detect_gpus())
    spec = default_catalog().get(MODEL)
    if gpu is None or installed_variant(real, spec, gpu) is None:
        pytest.skip("needs an NVIDIA GPU and the Z-Image Turbo model installed")

    port = _free_port()
    data = tmp_path_factory.mktemp("data")  # isolated gallery/db; real models and engine
    env = {
        **os.environ,
        "PHOTO_DATA_DIR": str(data),
        "PHOTO_MODELS_DIR": str(real.models),
        "PHOTO_PORT": str(port),
    }
    exe = Path(sys.executable).with_name("photo.exe" if os.name == "nt" else "photo")
    proc = subprocess.Popen([str(exe), "serve"], env=env)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/api/v1/system").json()["engine"]["state"] == "ready":
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            pytest.fail("engine did not become ready")
        yield base
    finally:
        proc.terminate()
        proc.wait(30)


def _generate(base: str, **params: object) -> tuple[dict, float]:
    body = {
        "model": MODEL,
        "prompt": "a red bicycle leaning on a brick wall, morning light",
        **params,
    }
    t0 = time.perf_counter()
    job = httpx.post(f"{base}/api/v1/jobs", json=body).raise_for_status().json()
    while True:
        job = httpx.get(f"{base}/api/v1/jobs/{job['id']}").json()
        if job["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.05)
    elapsed = time.perf_counter() - t0
    assert job["status"] == "succeeded", job["error"]
    return job, elapsed


def test_generate_on_gpu(server: str) -> None:
    _, cold = _generate(server, width=1024, height=1024, seed=1234)
    warm_job, warm = _generate(server, width=1024, height=1024, seed=1235)
    print(f"\n1024x1024, 8 steps: first run {cold:.2f}s (includes model load), warm {warm:.2f}s")

    image_id = warm_job["image_ids"][0]
    png = httpx.get(f"{server}/api/v1/images/{image_id}/file").content
    with Image.open(io.BytesIO(png)) as img:
        assert img.size == (1024, 1024)
        # A real picture, not a flat or black frame.
        extrema = img.convert("L").getextrema()
        assert extrema[1] - extrema[0] > 64
    meta = storage.read_metadata(png)
    assert meta is not None and meta["seed"] == 1235


def test_same_seed_is_reproducible(server: str) -> None:
    a, _ = _generate(server, width=768, height=768, seed=42)
    b, _ = _generate(server, width=768, height=768, seed=42)
    pa = httpx.get(f"{server}/api/v1/images/{a['image_ids'][0]}/file").content
    pb = httpx.get(f"{server}/api/v1/images/{b['image_ids'][0]}/file").content
    with Image.open(io.BytesIO(pa)) as ia, Image.open(io.BytesIO(pb)) as ib:
        assert ia.tobytes() == ib.tobytes()


def test_batch_and_widescreen(server: str) -> None:
    job, elapsed = _generate(server, width=1344, height=768, batch_size=4)
    print(f"\n4 x 1344x768: {elapsed:.2f}s")
    assert len(job["image_ids"]) == 4


def test_looks_and_references_on_gpu(server: str) -> None:
    """Enhanced prompt with a style, the detail pass, a variation and a reference picture."""
    enhanced, t_enh = _generate(
        server, width=1024, height=1024, seed=21, enhance=True, style="cinematic"
    )
    image_id = enhanced["image_ids"][0]
    info = httpx.get(f"{server}/api/v1/images/{image_id}").json()
    assert info["final_prompt"] and len(info["final_prompt"].split()) > 30

    detailed, t_det = _generate(server, width=1024, height=1024, seed=21, detail=True)
    big = httpx.get(f"{server}/api/v1/images/{detailed['image_ids'][0]}").json()
    assert (big["width"], big["height"]) == (1536, 1536)

    _, t_var = _generate(server, width=1024, height=1024, seed=22, variation_of=image_id)
    print(f"\nenhanced {t_enh:.1f}s, detail {t_det:.1f}s, variation {t_var:.1f}s")

    spec = default_catalog().get("flux2-klein-4b")
    if installed_variant(Settings(), spec, primary_gpu(detect_gpus())) is None:
        pytest.skip("FLUX.2 Klein not installed")
    _, t_ref = _generate(
        server, model="flux2-klein-4b", width=1024, height=1024, seed=5, references=[image_id]
    )
    print(f"klein with reference {t_ref:.1f}s")
