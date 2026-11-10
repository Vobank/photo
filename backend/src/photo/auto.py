"""Automatic mode: work out what kind of picture the user wants, then use the recipe and
model that are best at it.

A short, greedy (deterministic) language-model step classifies the request into a
*medium* and writes a faithful English version of it. Image models follow English far
better than other languages: in tests "робот-повар" came back as a human chef and
"ёжик" as a squirrel until the request was translated.

The routing table below comes from side-by-side comparisons on an RTX 5080
(see docs/auto-mode.md); change it only with new comparisons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

Medium = Literal[
    "photo", "anime", "cartoon", "illustration", "painting", "watercolor", "render3d", "graphic"
]
MEDIA: tuple[Medium, ...] = (
    "photo", "anime", "cartoon", "illustration", "painting", "watercolor", "render3d", "graphic",
)  # fmt: skip

AUTO = "auto"

# Each medium uses the style recipe of the same name (styles.py).
MEDIUM_STYLE: dict[Medium, str] = {m: m for m in MEDIA}

# Explicitly chosen styles still need a medium for model routing.
STYLE_MEDIUM: dict[str, Medium] = {
    "photo": "photo",
    "cinematic": "photo",
    "film": "photo",
    "portrait": "photo",
    "golden_hour": "photo",
    "noir": "photo",
    "neon": "photo",
    "product": "photo",
    "architecture": "photo",
    "fantasy": "painting",
    "anime": "anime",
    "cartoon": "cartoon",
    "illustration": "illustration",
    "painting": "painting",
    "watercolor": "watercolor",
    "render3d": "render3d",
    "graphic": "graphic",
}

# Preferred models per medium, best first. Models that are not installed, or cannot do
# what the request needs (references, detail pass, variations), are skipped.
MODEL_PREFERENCE: dict[Medium, tuple[str, ...]] = {
    # Klein: looks like a real, unstaged photo and keeps the requested framing.
    "photo": ("flux2-klein-4b", "z-image-turbo"),
    "anime": ("flux2-klein-4b", "z-image-turbo"),
    "cartoon": ("flux2-klein-4b", "z-image-turbo"),
    "illustration": ("flux2-klein-4b", "z-image-turbo"),
    "painting": ("flux2-klein-4b", "z-image-turbo"),
    "watercolor": ("flux2-klein-4b", "z-image-turbo"),
    # Z-Image: cleaner product-like 3D and much better logos and lettering.
    "render3d": ("z-image-turbo", "flux2-klein-4b"),
    "graphic": ("z-image-turbo", "flux2-klein-4b"),
}

CLASSIFY_SYSTEM = (
    "You prepare requests for an image generator. Reply with exactly one line in the form "
    "MEDIUM | PROMPT.\n"
    "MEDIUM is exactly one of:\n"
    "photo - a real photograph (the default when no other medium is asked for);\n"
    "render3d - anything 3D: CGI, Pixar or Disney-like 3D, clay, toy-like 3D figures;\n"
    "cartoon - 2D cartoon or comic, including 'cartoonish' when 3D is not mentioned;\n"
    "anime - only when anime or manga is asked for;\n"
    "illustration - drawing, sketch, children's book or editorial illustration;\n"
    "painting - oil, acrylic or classical painting;\n"
    "watercolor - watercolour painting;\n"
    "graphic - logo, icon, poster, sticker, lettering or other graphic design.\n"
    "PROMPT is a faithful English translation of the request: keep every subject, count, "
    "colour and quoted text exactly as written, keep the gender and age of every person "
    "(Russian 'подруги' are female friends, 'бабушка' is an old woman), add nothing, and drop "
    "the words that only name the medium.\n"
    "Examples:\n"
    "наклейка с котиком в очках -> graphic | a sticker of a kitten wearing glasses\n"
    'логотип пекарни «Хлеб» -> graphic | a bakery logo with the text "Хлеб"\n'
    "мультяшный дракон -> cartoon | a dragon\n"
    "робот в стиле Pixar -> render3d | a robot, Pixar-like 3D\n"
    "мультяшный ёжик в 3D -> render3d | a cartoonish hedgehog in 3D\n"
    "постер к фильму про пиратов -> graphic | a movie poster about pirates\n"
    "старик ловит рыбу на рассвете -> photo | an old man fishing at dawn\n"
    "подруги пьют чай на балконе -> photo | two female friends drinking tea on a balcony\n"
    "девушка с мечом, аниме -> anime | a girl with a sword"
)
CLASSIFY_MAX_TOKENS = 160

# What small models say instead of our exact labels.
_SYNONYMS: dict[str, Medium] = {
    "photograph": "photo",
    "photography": "photo",
    "realistic": "photo",
    "photorealistic": "photo",
    "manga": "anime",
    "comic": "cartoon",
    "cartoons": "cartoon",
    "drawing": "illustration",
    "sketch": "illustration",
    "art": "illustration",
    "oil": "painting",
    "oil painting": "painting",
    "watercolour": "watercolor",
    "3d": "render3d",
    "3d render": "render3d",
    "render": "render3d",
    "cgi": "render3d",
    "logo": "graphic",
    "icon": "graphic",
    "poster": "graphic",
    "sticker": "graphic",
    "lettering": "graphic",
    "typography": "graphic",
    "design": "graphic",
    "graphic design": "graphic",
}


@dataclass(frozen=True, slots=True)
class Classification:
    medium: Medium
    prompt: str  # English; the original request when the model's answer was unusable
    understood: bool  # False when we fell back


def _medium(label: str) -> Medium | None:
    key = re.sub(r"[^a-z0-9 ]", "", label.lower()).strip()
    for candidate in (key, key.removesuffix("s")):  # "stickers", "logos", "photos"
        if candidate in MEDIA:
            return candidate
        if candidate in _SYNONYMS:
            return _SYNONYMS[candidate]
    return None


def parse_classification(answer: str, original: str) -> Classification:
    """Read ``MEDIUM | PROMPT``. Never raises: a bad answer means photo + the original text."""
    line = next((ln.strip() for ln in answer.strip().splitlines() if "|" in ln), "")
    if line:
        label, _, text = line.partition("|")
        medium = _medium(label)
    else:
        # No separator: accept "poster for a movie…" if it opens with a medium word.
        text = answer.strip().splitlines()[0].strip() if answer.strip() else ""
        medium = _medium(text.split(" ", 1)[0]) if text else None
    text = text.strip()
    # Unwrap only a fully quoted answer; quotes inside are lettering the user asked for.
    if len(text) >= 2 and text[0] == text[-1] == '"' and text.count('"') == 2:
        text = text[1:-1].strip()
    # A translation much shorter than the request probably lost content; keep the original.
    if medium is None or not text or len(text) < len(original.strip()) * 0.35:
        return Classification(medium or "photo", original, understood=False)
    return Classification(medium, text, understood=True)


def route(medium: Medium, candidates: list[str]) -> str | None:
    """First preferred model among ``candidates`` (installed and capable)."""
    for model_id in MODEL_PREFERENCE[medium]:
        if model_id in candidates:
            return model_id
    return candidates[0] if candidates else None
