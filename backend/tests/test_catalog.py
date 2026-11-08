import pytest
from pydantic import ValidationError

from photo.catalog import Catalog, default_catalog
from photo.hardware import Gpu

from .conftest import RTX_4060, RTX_5080


def test_catalog_loads_and_is_consistent() -> None:
    catalog = default_catalog()
    assert catalog.models, "catalog must not be empty"
    for m in catalog.models:
        for v in m.variants:
            assert m.variant_files(v)  # every reference resolves


def test_blackwell_prefers_nvfp4() -> None:
    spec = default_catalog().get("z-image-turbo")
    assert spec.choose_variant(RTX_5080).id == "nvfp4"


def test_ada_never_gets_nvfp4() -> None:
    spec = default_catalog().get("z-image-turbo")
    ada_16 = Gpu(0, "RTX 4080", 16376, "581.0", "8.9")
    assert spec.choose_variant(ada_16).id == "bf16"
    # 8 GB Ada: nothing fits, falls back to the most compatible (last) variant.
    assert spec.choose_variant(RTX_4060).id == "bf16"


def test_urls_are_pinned_to_revision() -> None:
    spec = default_catalog().get("z-image-turbo")
    f = spec.files["vae"]
    assert f.url("https://huggingface.co/") == (
        f"https://huggingface.co/Comfy-Org/z_image_turbo/resolve/{f.revision}/split_files/vae/ae.safetensors"
    )


def test_same_filename_with_different_hash_is_rejected() -> None:
    raw = default_catalog().model_dump(by_alias=True)
    clone = dict(raw["models"][0], id="clone")
    clone["files"] = {k: dict(v) for k, v in clone["files"].items()}
    clone["files"]["vae"]["sha256"] = "0" * 64
    raw["models"] = [raw["models"][0], clone]
    with pytest.raises(ValidationError, match="different hashes"):
        Catalog.model_validate(raw)


def test_unsafe_file_name_rejected() -> None:
    raw = default_catalog().model_dump(by_alias=True)
    raw["models"][0]["files"]["vae"]["name"] = "../../evil.safetensors"
    with pytest.raises(ValidationError):
        Catalog.model_validate(raw)
