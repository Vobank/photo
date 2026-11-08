from pathlib import Path

import pytest
from PIL import Image

from photo import storage
from photo.db import MIGRATIONS, Database
from photo.ids import is_valid_id, new_id

from .conftest import png_bytes


def test_save_result_embeds_parameters(tmp_path: Path) -> None:
    meta = {
        "params": {"prompt": "кот на крыше", "width": 64, "height": 48, "model": "m"},
        "seed": 7,
    }
    stored = storage.save_result(tmp_path, "abc", png_bytes(), meta)
    data = (tmp_path / stored.path).read_bytes()
    assert storage.read_metadata(data) == meta
    with Image.open(tmp_path / stored.path) as img:
        assert img.text["parameters"].startswith("кот на крыше")
        assert "prompt" not in img.text  # engine graph metadata must not leak
    with Image.open(tmp_path / stored.thumb_path) as thumb:
        assert thumb.format == "WEBP"
    assert (stored.width, stored.height) == (64, 48)


def test_read_metadata_of_foreign_image_is_none() -> None:
    assert storage.read_metadata(png_bytes()) is None
    assert storage.read_metadata(b"not an image") is None


def test_resolve_blocks_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        storage.resolve(tmp_path, "../secret.txt")
    assert storage.resolve(tmp_path, "2026/11/x.png") == (tmp_path / "2026/11/x.png").resolve()


def test_ids_sortable_and_valid() -> None:
    ids = [new_id() for _ in range(200)]
    assert all(is_valid_id(i) for i in ids)
    assert len(set(ids)) == 200
    assert not is_valid_id("../../etc/passwd")


def test_db_migrates_and_reopens(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    assert db.one("PRAGMA user_version")[0] == len(MIGRATIONS)
    db.close()
    db = Database(tmp_path / "x.db")  # idempotent
    assert db.one("PRAGMA journal_mode")[0] == "wal"
    db.close()


def test_db_from_newer_version_refuses(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 5}")
    db.close()
    with pytest.raises(RuntimeError, match="newer version"):
        Database(tmp_path / "x.db")


def test_transaction_rolls_back(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    with pytest.raises(ZeroDivisionError), db.transaction() as tx:
        tx.execute(
            "INSERT INTO jobs (id, kind, status, params, model, variant, seed, created_at) "
            "VALUES ('a','generate','queued','{}','m','v',1,0)"
        )
        _ = 1 / 0
    assert db.one("SELECT COUNT(*) FROM jobs")[0] == 0
    db.close()
