import json
import struct

from photo.engine.client import parse_binary_frame
from photo.engine.process import build_command
from photo.events import encode_preview

from .conftest import RTX_5080


def test_parse_legacy_preview() -> None:
    frame = struct.pack(">II", 1, 2) + b"PNGDATA"
    preview, pid = parse_binary_frame(frame)  # type: ignore[misc]
    assert (preview.mime, preview.data, pid) == ("image/png", b"PNGDATA", None)


def test_parse_preview_with_metadata() -> None:
    meta = json.dumps({"prompt_id": "p1", "image_type": "image/jpeg"}).encode()
    frame = struct.pack(">II", 4, len(meta)) + meta + b"JPG"
    preview, pid = parse_binary_frame(frame)  # type: ignore[misc]
    assert (preview.mime, preview.data, pid) == ("image/jpeg", b"JPG", "p1")


def test_parse_rejects_truncated_and_unknown() -> None:
    assert parse_binary_frame(b"\x00\x00") is None
    assert parse_binary_frame(struct.pack(">II", 4, 999) + b"{}") is None
    assert parse_binary_frame(struct.pack(">II", 3, 0)) is None


def test_encode_preview_roundtrip() -> None:
    data = encode_preview("job1", "image/jpeg", b"IMG")
    (n,) = struct.unpack(">I", data[:4])
    assert json.loads(data[4 : 4 + n]) == {
        "type": "preview",
        "job_id": "job1",
        "mime": "image/jpeg",
    }
    assert data[4 + n :] == b"IMG"


def test_engine_command_is_local_only(settings) -> None:  # type: ignore[no-untyped-def]
    cmd = build_command(settings, 12345, RTX_5080)
    assert cmd[cmd.index("--listen") + 1] == "127.0.0.1"
    assert "--disable-api-nodes" in cmd
    assert cmd[cmd.index("--models-directory") + 1] == str(settings.models)
    assert cmd[cmd.index("--cuda-device") + 1] == "0"
