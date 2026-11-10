"""What the image model is told for each edit action.

Chosen from side-by-side runs on an RTX 5080 (docs/editing.md):

* The model edits *with the picture as a reference* (FLUX.2 Klein's editing mode). Plain
  masked inpainting without the reference invented unrelated scenery.
* For area edits the model redraws a context crop and only the selection is blended
  back (see editing.py), so nothing outside the selection can change.
* Removal works best as a plain instruction. Marking the area on the reference (grey
  fill, red outline) made the model faithfully keep the mark.
"""

from __future__ import annotations

import re

from photo.schemas import EditParams

TRANSLATE_SYSTEM = (
    "Translate the user's image-editing instruction into clear English. Keep every object, "
    "colour, count and quoted text exactly; add nothing. Output only the translation."
)
TRANSLATE_MAX_TOKENS = 200

_NON_ASCII_LETTER = re.compile(r"[^\x00-\x7f]")


def needs_translation(text: str) -> bool:
    return bool(_NON_ASCII_LETTER.search(text))


def clean_translation(answer: str, original: str) -> str:
    """The model's translation, or the original if the answer looks unusable."""
    text = answer.strip().splitlines()[0].strip() if answer.strip() else ""
    if len(text) >= 2 and text[0] == text[-1] == '"' and text.count('"') == 2:
        text = text[1:-1].strip()
    if not text or len(text) < len(original) * 0.3 or len(text) > len(original) * 4 + 40:
        return original
    return text


def instruction(params: EditParams, prompt: str) -> str:
    """The sentence the image model receives. ``prompt`` is already in English."""
    prompt = prompt.strip().rstrip(".")
    area = params.mask is not None
    if params.action == "remove":
        what = prompt or "the selected object"
        return (
            f"Remove {what} completely and fill the area with the background that would "
            "naturally be behind it. Keep everything else unchanged."
        )
    if area:
        return f"{prompt}. Keep everything else unchanged."
    return f"{prompt}."
