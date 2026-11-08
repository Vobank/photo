import hashlib
from pathlib import Path

import httpx
import pytest

from photo import downloads
from photo.downloads import DownloadRequest, IntegrityError, download

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB
SHA = hashlib.sha256(PAYLOAD).hexdigest()


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def instant(_: float) -> None:
        return None

    monkeypatch.setattr(downloads.asyncio, "sleep", instant)


def server(*, honour_range: bool = True, drop_after: int | None = None, body: bytes = PAYLOAD):
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        rng = request.headers.get("range")
        calls.append(rng)
        start = int(rng.split("=")[1].rstrip("-")) if rng and honour_range else 0
        chunk = body[start:]
        if drop_after is not None and len(calls) == 1:
            chunk = chunk[:drop_after]  # simulate a connection cut mid-stream
        status = 206 if start else 200
        return httpx.Response(status, content=chunk)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def req(tmp_path: Path, sha: str = SHA) -> DownloadRequest:
    return DownloadRequest("https://hf.test/f", tmp_path / "m" / "f.safetensors", len(PAYLOAD), sha)


async def test_downloads_and_verifies(tmp_path: Path) -> None:
    http, _ = server()
    seen: list[int] = []
    path = await download(req(tmp_path), lambda d, _t: seen.append(d), client=http)
    assert path.read_bytes() == PAYLOAD
    assert seen[-1] == len(PAYLOAD)
    assert not path.with_name("f.safetensors.part").exists()


async def test_resumes_after_cut(tmp_path: Path) -> None:
    http, calls = server(drop_after=300_000)
    path = await download(req(tmp_path), client=http)
    assert path.read_bytes() == PAYLOAD
    assert calls == [None, "bytes=300000-"]


async def test_resumes_existing_part_file(tmp_path: Path) -> None:
    r = req(tmp_path)
    r.dest.parent.mkdir(parents=True)
    r.dest.with_name("f.safetensors.part").write_bytes(PAYLOAD[:1000])
    http, calls = server()
    await download(r, client=http)
    assert calls == ["bytes=1000-"]
    assert r.dest.read_bytes() == PAYLOAD


async def test_server_ignoring_range_restarts_cleanly(tmp_path: Path) -> None:
    r = req(tmp_path)
    r.dest.parent.mkdir(parents=True)
    r.dest.with_name("f.safetensors.part").write_bytes(PAYLOAD[:1000])
    http, _ = server(honour_range=False)
    await download(r, client=http)
    assert r.dest.read_bytes() == PAYLOAD


async def test_checksum_mismatch_deletes_part(tmp_path: Path) -> None:
    http, _ = server()
    r = req(tmp_path, sha="0" * 64)
    with pytest.raises(IntegrityError):
        await download(r, client=http)
    assert not r.dest.exists()
    assert not r.dest.with_name("f.safetensors.part").exists()


async def test_existing_complete_file_is_not_downloaded(tmp_path: Path) -> None:
    r = req(tmp_path)
    r.dest.parent.mkdir(parents=True)
    r.dest.write_bytes(PAYLOAD)
    http, calls = server()
    await download(r, client=http)
    assert calls == []


async def test_forbidden_gives_actionable_error(tmp_path: Path) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(403)))
    with pytest.raises(downloads.DownloadError, match="licence"):
        await download(req(tmp_path), client=http)


def test_not_enough_space(tmp_path: Path) -> None:
    with pytest.raises(downloads.NotEnoughSpaceError):
        downloads.ensure_space(tmp_path, 1 << 60)
