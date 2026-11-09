from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from photo import installer, prefs
from photo import setup as steps
from photo.api.app import create_setup_app
from photo.config import Settings
from photo.disks import Disk
from photo.downloads import DownloadRequest
from photo.events import EventBus
from photo.installer import InstallConfig, SetupRunner

from .conftest import RTX_5080, TINY_SIZE, tiny_catalog


@pytest.fixture
def fake_disks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[Disk]:
    root = tmp_path.anchor
    disks = [Disk(root, "System", "fixed", 10**12, 10**11)]
    monkeypatch.setattr(installer, "list_disks", lambda: disks)
    # Never depend on the real free space of the machine running the tests.
    monkeypatch.setattr(installer, "free_space", lambda _p: 10**11)
    return disks


def make_runner(settings: Settings) -> SetupRunner:
    return SetupRunner(settings, tiny_catalog(), EventBus(), RTX_5080)


def cfg(tmp_path: Path, **kw: object) -> InstallConfig:
    base = {
        "language": "de",
        "models_dir": str(tmp_path / "m"),
        "data_dir": str(tmp_path / "d"),
        "engine_env_dir": str(tmp_path / "env"),
        "models": ["z-image-turbo"],
    }
    return InstallConfig.model_validate({**base, **kw})


# ---- prefs ---------------------------------------------------------------------------


def test_prefs_roundtrip_keeps_hand_written_keys(isolated_config: Path) -> None:
    isolated_config.write_text('hf_token = "secret"\nport = 7999\n', encoding="utf-8")
    prefs.update({"language": "ja", "models_dir": Path(r"D:\Мои модели\photo")})
    data = prefs.read()
    assert data == {
        "hf_token": "secret",
        "port": 7999,
        "language": "ja",
        "models_dir": r"D:\Мои модели\photo",
    }
    prefs.update({"language": None})
    assert "language" not in prefs.read()


def test_prefs_refuses_unknown_keys() -> None:
    with pytest.raises(ValueError, match="not writable"):
        prefs.update({"access_token": "x"})


def test_settings_pick_up_saved_choices(isolated_config: Path, tmp_path: Path) -> None:
    prefs.update({"language": "ko", "engine_env_dir": tmp_path / "env"})
    s = Settings(home=tmp_path)
    assert s.language == "ko"
    assert s.engine_env == (tmp_path / "env").resolve()
    assert Settings(home=tmp_path, language="xx").language == "en"


# ---- validation ----------------------------------------------------------------------


def test_valid_config_passes(settings: Settings, tmp_path: Path, fake_disks: list[Disk]) -> None:
    assert make_runner(settings).validate(cfg(tmp_path)) == []


def test_validation_codes(settings: Settings, tmp_path: Path, fake_disks: list[Disk]) -> None:
    (tmp_path / "afile").write_text("x")
    errors = make_runner(settings).validate(
        cfg(
            tmp_path,
            language="xx",
            models_dir="relative/path",
            data_dir=str(tmp_path / "afile"),
            models=["nope"],
        )
    )
    codes = {(e.field, e.code) for e in errors}
    assert ("language", "unsupported_language") in codes
    assert ("models", "unknown_model") in codes
    assert ("models_dir", "path_not_absolute") in codes
    assert ("data_dir", "path_is_file") in codes


@pytest.mark.skipif(os.name != "nt", reason="Windows system folders")
def test_system_folders_refused(settings: Settings, tmp_path: Path, fake_disks: list[Disk]) -> None:
    errors = make_runner(settings).validate(cfg(tmp_path, models_dir=r"C:\Windows\photo"))
    assert [(e.field, e.code) for e in errors] == [("models_dir", "path_system_folder")]


def test_not_enough_space(
    settings: Settings, tmp_path: Path, fake_disks: list[Disk], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(installer, "free_space", lambda _p: 1_000)
    errors = make_runner(settings).validate(cfg(tmp_path))
    assert {e.code for e in errors} == {"not_enough_space"}
    assert {e.field for e in errors} >= {"models_dir", "engine_env_dir"}


# ---- running -------------------------------------------------------------------------


@pytest.fixture
def fake_steps(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(steps, "installed_engine_commit", lambda s: steps.engine_pin(s).commit)
    monkeypatch.setattr(
        steps, "engine_pin", lambda s: steps.EnginePin("v0", "c" * 40, "u", "0" * 64, 1)
    )
    monkeypatch.setattr(steps, "find_uv", lambda s: "uv")

    async def fake_sync(s: Settings, uv: str, on_line: Callable[[str], None]) -> None:
        calls.append(f"sync:{s.engine_env}")
        on_line("Installed 103 packages")

    monkeypatch.setattr(steps, "sync_engine_env_streaming", fake_sync)
    monkeypatch.setattr(steps, "verify_engine_cuda", lambda s: "torch ok")

    async def fake_download(
        req: DownloadRequest, progress: object = None, client: object = None
    ) -> Path:
        calls.append(f"download:{req.dest.name}")
        req.dest.parent.mkdir(parents=True, exist_ok=True)
        req.dest.write_bytes(bytes(req.size))
        return req.dest

    monkeypatch.setattr(installer, "download", fake_download)
    return calls


async def _run(runner: SetupRunner, c: InstallConfig) -> None:
    runner.start(c)
    assert runner._task is not None
    await runner._task


async def test_full_run_writes_choices_and_downloads(
    settings: Settings, tmp_path: Path, fake_steps: list[str], isolated_config: Path
) -> None:
    runner = make_runner(settings)
    await _run(runner, cfg(tmp_path))
    assert runner.state.status == "done", runner.state.error
    assert [s.status for s in runner.state.steps] == ["skipped", "done", "done", "done"]
    assert prefs.read()["language"] == "de"
    assert prefs.read()["models_dir"] == str(tmp_path / "m")
    assert sum(c.startswith("download:") for c in fake_steps) == 3
    assert (tmp_path / "m" / "vae" / "ae.safetensors").stat().st_size == TINY_SIZE

    # Re-running is a repair: nothing to download again.
    fake_steps.clear()
    await _run(runner, cfg(tmp_path))
    assert runner.state.step("models").status == "skipped"
    assert not any(c.startswith("download:") for c in fake_steps)


async def test_changing_models_drive_moves_files_instead_of_downloading(
    settings: Settings, tmp_path: Path, fake_steps: list[str]
) -> None:
    runner = make_runner(settings)
    await _run(runner, cfg(tmp_path))
    fake_steps.clear()
    await _run(runner, cfg(tmp_path, models_dir=str(tmp_path / "elsewhere")))
    assert runner.state.status == "done"
    assert not any(c.startswith("download:") for c in fake_steps)
    assert (tmp_path / "elsewhere" / "vae" / "ae.safetensors").exists()
    assert not (tmp_path / "m" / "vae" / "ae.safetensors").exists()


async def test_failure_reports_code_and_step(
    settings: Settings, tmp_path: Path, fake_steps: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(s: Settings) -> str:
        raise steps.SetupError("no cuda", "cuda_unavailable")

    monkeypatch.setattr(steps, "verify_engine_cuda", broken)
    runner = make_runner(settings)
    await _run(runner, cfg(tmp_path))
    assert runner.state.status == "failed"
    assert runner.state.error == {"code": "cuda_unavailable", "detail": "no cuda", "step": "gpu"}
    assert runner.state.step("gpu").status == "failed"


# ---- HTTP ----------------------------------------------------------------------------


def test_setup_routes(
    settings: Settings, tmp_path: Path, fake_disks: list[Disk], fake_steps: list[str]
) -> None:
    runner = make_runner(settings)
    exited: list[bool] = []
    app = create_setup_app(settings, runner, runner.bus, lambda: exited.append(True))
    with TestClient(app, base_url="http://127.0.0.1:7860", client=("127.0.0.1", 5000)) as c:
        assert c.get("/api/v1/system").json()["mode"] == "setup"
        plan = c.get("/api/v1/setup").json()
        assert len(plan["languages"]) == 12 and plan["languages"][0] == "en"
        assert plan["models"][0]["id"] == "z-image-turbo"
        assert plan["gpu"]["driver_ok"] is True

        bad = c.post(
            "/api/v1/setup/start", json={**cfg(tmp_path).model_dump(), "models_dir": "rel"}
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["fields"][0]["code"] == "path_not_absolute"

        assert c.post("/api/v1/setup/finish").status_code == 409

        r = c.post("/api/v1/setup/start", json=cfg(tmp_path).model_dump())
        assert r.status_code == 202
        for _ in range(100):
            if c.get("/api/v1/setup").json()["run"]["status"] == "done":
                break
            asyncio.run(asyncio.sleep(0.02))
        assert c.post("/api/v1/setup/finish").status_code == 202
