"""Application settings.

Resolution order (later wins): defaults → ``<home>/photo.toml`` → ``PHOTO_*`` env vars.
``home`` is the install root: the folder holding ``backend/``, ``frontend/`` and the
runtime folders. It is derived from this file's location unless ``PHOTO_HOME`` is set.
"""

from __future__ import annotations

import os
from functools import cached_property
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# backend/src/photo/config.py → parents[3] is the repository / install root.
_SOURCE_ROOT = Path(__file__).resolve().parents[3]


def default_home() -> Path:
    env = os.environ.get("PHOTO_HOME")
    return Path(env).expanduser().resolve() if env else _SOURCE_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOTO_", extra="ignore", frozen=True)

    home: Path = Field(default_factory=default_home)
    data_dir: Path | None = None
    models_dir: Path | None = None
    runtime_dir: Path | None = None

    host: str = "127.0.0.1"
    port: int = Field(default=7860, ge=1, le=65535)
    # Extra hostnames allowed in the Host header (e.g. a LAN name). Loopback is always allowed.
    allowed_hosts: tuple[str, ...] = ()
    # Required for any non-loopback client when host is not loopback.
    access_token: str | None = None

    engine_port: int | None = Field(default=None, ge=1, le=65535)
    engine_extra_args: tuple[str, ...] = ()
    engine_start_timeout_s: float = 180.0

    hf_endpoint: str = "https://huggingface.co"
    hf_token: str | None = None

    @model_validator(mode="after")
    def _fill_dirs(self) -> Self:
        # frozen model: bypass immutability once, during construction only.
        object.__setattr__(self, "data_dir", (self.data_dir or self.home / "data").resolve())
        object.__setattr__(self, "models_dir", (self.models_dir or self.home / "models").resolve())
        object.__setattr__(
            self, "runtime_dir", (self.runtime_dir or self.home / "runtime").resolve()
        )
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, toml_file=default_home() / "photo.toml")
        return (init_settings, env_settings, toml)

    # ---- derived paths -------------------------------------------------------------

    @property
    def data(self) -> Path:
        assert self.data_dir is not None
        return self.data_dir

    @property
    def models(self) -> Path:
        assert self.models_dir is not None
        return self.models_dir

    @property
    def runtime(self) -> Path:
        assert self.runtime_dir is not None
        return self.runtime_dir

    @cached_property
    def database_path(self) -> Path:
        return self.data / "photo.db"

    @cached_property
    def images_dir(self) -> Path:
        return self.data / "images"

    @cached_property
    def uploads_dir(self) -> Path:
        return self.data / "uploads"

    @cached_property
    def logs_dir(self) -> Path:
        return self.data / "logs"

    @cached_property
    def engine_source_dir(self) -> Path:
        return self.runtime / "comfyui"

    @cached_property
    def engine_state_dir(self) -> Path:
        """Scratch folders the engine writes to (output, temp, input, user)."""
        return self.runtime / "engine-state"

    @cached_property
    def engine_python(self) -> Path:
        venv = self.home / "engine" / ".venv"
        return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @cached_property
    def frontend_dist(self) -> Path:
        return self.home / "frontend" / "dist"

    def ensure_dirs(self) -> None:
        for d in (self.data, self.images_dir, self.uploads_dir, self.logs_dir, self.models):
            d.mkdir(parents=True, exist_ok=True)


def is_loopback_host(host: str) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}
