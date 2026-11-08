"""Typed access to ``models.toml`` and variant selection."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from photo.hardware import Arch, Gpu

Task = Literal["generate", "edit", "inpaint", "upscale", "remove_background"]

_CATALOG_FILE = Path(__file__).with_name("models.toml")
_SHA256_LEN = 64


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelFile(_Frozen):
    dir: Literal[
        "diffusion_models", "text_encoders", "vae", "loras", "upscale_models", "checkpoints"
    ]
    name: str = Field(pattern=r"^[A-Za-z0-9._-]+$")
    repo: str
    revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    path: str
    size: int = Field(gt=0)
    sha256: str = Field(min_length=_SHA256_LEN, max_length=_SHA256_LEN, pattern=r"^[0-9a-f]+$")

    @property
    def relative_path(self) -> Path:
        return Path(self.dir) / self.name

    def url(self, endpoint: str) -> str:
        return f"{endpoint.rstrip('/')}/{self.repo}/resolve/{self.revision}/{self.path}"


class Defaults(_Frozen):
    steps: int = 20
    cfg: float = 1.0
    sampler: str = "euler"
    scheduler: str = "simple"
    shift: float | None = None


class Variant(_Frozen):
    id: str
    label: str
    archs: tuple[Arch, ...] = ()
    min_vram_gb: float = 0
    files: dict[str, str]  # role → file key

    def fits(self, gpu: Gpu | None) -> bool:
        if gpu is None:
            return False
        if self.archs and gpu.arch not in self.archs:
            return False
        return gpu.vram_gb + 0.5 >= self.min_vram_gb  # vendors round VRAM down


class ModelSpec(_Frozen):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    vendor: str
    description: str
    tasks: tuple[Task, ...]
    pipeline: str
    license: str
    license_url: str
    commercial_use: bool
    defaults: Defaults = Defaults()
    files: dict[str, ModelFile]
    variants: tuple[Variant, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_refs(self) -> Self:
        for v in self.variants:
            missing = set(v.files.values()) - self.files.keys()
            if missing:
                raise ValueError(f"{self.id}/{v.id} references unknown files {sorted(missing)}")
        return self

    def variant(self, variant_id: str) -> Variant:
        for v in self.variants:
            if v.id == variant_id:
                return v
        raise KeyError(f"{self.id} has no variant {variant_id!r}")

    def choose_variant(self, gpu: Gpu | None) -> Variant:
        """Best variant for this GPU; the last (most compatible) one if nothing fits."""
        for v in self.variants:
            if v.fits(gpu):
                return v
        return self.variants[-1]

    def variant_files(self, variant: Variant) -> dict[str, ModelFile]:
        return {role: self.files[key] for role, key in variant.files.items()}


class Catalog(_Frozen):
    schema_: int = Field(alias="schema")
    models: tuple[ModelSpec, ...]

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [m.id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate model ids in catalog")
        # Same filename must mean the same bytes everywhere.
        by_name: dict[str, str] = {}
        for m in self.models:
            for f in m.files.values():
                if by_name.setdefault(f.name, f.sha256) != f.sha256:
                    raise ValueError(f"file name {f.name} used with different hashes")
        return self

    def get(self, model_id: str) -> ModelSpec:
        for m in self.models:
            if m.id == model_id:
                return m
        raise KeyError(model_id)


def load_catalog(path: Path = _CATALOG_FILE) -> Catalog:
    with path.open("rb") as fh:
        return Catalog.model_validate(tomllib.load(fh))


@cache
def default_catalog() -> Catalog:
    return load_catalog()


def is_installed(models_dir: Path, f: ModelFile) -> bool:
    """Cheap check (size only). Hashes are verified at download time."""
    p = models_dir / f.relative_path
    try:
        return p.stat().st_size == f.size
    except OSError:
        return False
