"""Public, versioned request/response shapes shared by the API and the job system."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# JavaScript numbers are exact only up to 2**53 - 1; seeds round-trip through the UI.
MAX_SEED = 2**53 - 1
MAX_PIXELS = 2048 * 2048

Dimension = Annotated[int, Field(ge=256, le=2048, multiple_of=16)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerateParams(_Strict):
    """Text-to-image. Unset sampling fields fall back to the model's defaults."""

    kind: Literal["generate"] = "generate"
    model: str = Field(pattern=r"^[a-z0-9-]+$", max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)
    negative_prompt: str = Field(default="", max_length=4000)
    width: Dimension = 1024
    height: Dimension = 1024
    seed: int | None = Field(default=None, ge=0, le=MAX_SEED)
    batch_size: int = Field(default=1, ge=1, le=4)
    steps: int | None = Field(default=None, ge=1, le=100)
    cfg: float | None = Field(default=None, ge=0, le=30)

    @model_validator(mode="after")
    def _pixel_budget(self) -> GenerateParams:
        if self.width * self.height > MAX_PIXELS:
            raise ValueError(f"width × height must not exceed {MAX_PIXELS} pixels")
        return self


# Becomes a discriminated union on `kind` as edit/upscale/... job kinds are added.
type JobParams = GenerateParams

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
