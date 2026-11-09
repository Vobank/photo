"""Public, versioned request/response shapes shared by the API and the job system."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# JavaScript numbers are exact only up to 2**53 - 1; seeds round-trip through the UI.
MAX_SEED = 2**53 - 1
MAX_PIXELS = 2048 * 2048

MAX_REFERENCES = 4

Dimension = Annotated[int, Field(ge=256, le=2048, multiple_of=16)]
# Time-sortable ids (see ids.py): 26 lowercase Crockford base32 characters.
Id = Annotated[str, Field(pattern=r"^[0-9a-hjkmnp-tv-z]{26}$")]


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

    # Look: a curated style preset (see styles.py) appended to the prompt.
    style: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=32)
    # Let the language model expand the prompt (and translate it to English) first.
    enhance: bool = False
    # Second pass at a higher resolution for finer detail.
    detail: bool = False

    # Pictures the result should follow (style, subject, product…). Gallery image or
    # upload ids; needs a model with the "reference" task.
    references: list[Id] = Field(default_factory=list, max_length=MAX_REFERENCES)
    # Image-to-image: start from this picture and keep its composition and colours.
    variation_of: Id | None = None
    # 0 = return the source unchanged, 1 = ignore it entirely.
    variation_strength: float = Field(default=0.55, ge=0.05, le=0.95)

    @model_validator(mode="after")
    def _checks(self) -> GenerateParams:
        if self.width * self.height > MAX_PIXELS:
            raise ValueError(f"width × height must not exceed {MAX_PIXELS} pixels")
        if self.references and self.variation_of:
            raise ValueError("use either references or variation_of, not both")
        if len(set(self.references)) != len(self.references):
            raise ValueError("references must not repeat")
        return self


# Becomes a discriminated union on `kind` as edit/upscale/... job kinds are added.
type JobParams = GenerateParams

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled"})
