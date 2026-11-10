"""Curated looks and the prompt-enhancement instructions.

Style text is English on purpose: both image models follow English (and Chinese)
best, and the UI translates only the style *names*. Each style has two parts:

* ``suffix`` — appended to the prompt when enhancement is off;
* ``direction`` — handed to the language model when enhancement is on, so it can
  weave the look into the scene instead of bolting keywords onto the end.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Style:
    id: str
    suffix: str
    direction: str
    # Used instead of ``suffix`` when the prompt is about people (see mentions_people).
    people_suffix: str | None = None


# Realism for people, chosen from side-by-side runs (docs/realism.md). Describing the
# *skin* as real removes the airbrushed "AI face"; the quality words keep it crisp and
# deep instead of flat and noisy ("raw unedited photo" did that). Words such as
# "wrinkles", "blemishes" or "cluttered" were left out because they aged people and
# dirtied scenes. Never added without people: it made a person appear by a mountain lake.
PEOPLE_REALISM = (
    "real skin with visible pores and natural imperfections, natural hair with flyaways, "
    "candid unposed moment, ordinary real person, true-to-life colors, sharp focus, crisp "
    "detail, clear depth and dimension, directional natural light, clean image without noise"
)
# Shorter version that other photographic looks (cinematic, noir...) append for people.
PEOPLE_REALISM_SHORT = "real skin with visible pores, natural unposed expression, unretouched"

_PEOPLE_EN = re.compile(
    r"\b(?:man|men|woman|women|person|people|persons|girl|girls|boy|boys|child|children|kid|"
    r"kids|baby|babies|toddler|teen|teenager|family|couple|friends?|portrait|face|faces|selfie|"
    r"crowd|guy|guys|lady|ladies|gentleman|grandma|grandmother|grandpa|grandfather|mother|"
    r"father|mom|mum|dad|daughter|son|sister|brother|wife|husband|bride|groom|student|"
    r"students|worker|workers|doctor|nurse|teacher|chef|cook|waiter|waitress|farmer|fisherman|"
    r"soldier|police(?:man|woman)?|officer|dancer|athlete|player|musician|singer|pedestrians?|"
    r"passengers?|tourists?|elderly|old-timer|he|she|his|her)\b",
    re.IGNORECASE,
)
_PEOPLE_RU = re.compile(
    r"(?:человек|люд[иейям]|мужчин|женщин|девушк|девочк|парн|парен|мальчик|ребён|ребен|"
    r"дети|детей|семь[яиейю]|портрет|лицо|лица|бабушк|дедушк|мама|маму|папа|друз|подруг|"
    r"студент|рабоч|врач|рыбак|старик|старушк|невест|жених|толп|прохож|пассажир|школьни|"
    r"подрост|солдат|полицейск|медсестр|учител|танцор|спортсмен|музыкант|певиц|певец)",
    re.IGNORECASE,
)


def mentions_people(text: str) -> bool:
    """Whether a request is (also) about people. English after translation, Russian before."""
    return bool(_PEOPLE_EN.search(text) or _PEOPLE_RU.search(text))


STYLES: tuple[Style, ...] = (
    Style(
        "photo",
        # No grain, no "imperfections": they made pictures noisy, milky and flat. No camera
        # nouns either: Z-Image drew a camera into the scene (docs/realism.md).
        "professional photograph, crisp fine detail, natural vibrant colors, deep contrast with "
        "clear depth and dimension, directional natural light with soft shadows, atmospheric "
        "perspective, clean image without noise",
        "a genuine photograph by a skilled photographer: crisp fine detail, natural vibrant "
        "colour, deep contrast, clear depth and dimension, directional natural light with soft "
        "shadows and atmospheric perspective, a clean image without noise. Describe real-world "
        "materials and light precisely. Keep the framing the idea implies. If there are people, "
        "they look like real, ordinary people caught in a candid moment: real skin with visible "
        "pores and natural imperfections, natural hair, unposed expressions, never "
        "model-perfect or symmetrical. It must look like a real photo, never like a glossy, "
        "airbrushed render",
        people_suffix=PEOPLE_REALISM,
    ),
    Style(
        "cinematic",
        "cinematic film still, anamorphic lens, shallow depth of field, motivated dramatic "
        "lighting, rich colour grade, subtle atmospheric haze, fine film grain",
        "a frame from a big-budget film: anamorphic lens, shallow depth of field, motivated "
        "dramatic light, atmospheric haze and a deliberate colour grade",
    ),
    Style(
        "film",
        "shot on 35mm Kodak Portra 400, natural film grain, soft highlight roll-off, true-to-life "
        "colour, candid composition",
        "an analog 35mm photograph on Kodak Portra 400 with natural grain, soft highlights and "
        "honest, unretouched colour; candid rather than posed",
    ),
    Style(
        "portrait",
        "editorial portrait, 85mm lens at f/1.8, soft key light with a gentle rim light, crisp "
        "detail in the eyes and natural skin texture, magazine quality",
        "an editorial magazine portrait: 85mm lens wide open, soft key light and a rim light, "
        "sharp eyes, natural skin texture, a background that falls into soft blur",
    ),
    Style(
        "golden_hour",
        "golden hour, low warm sun, long soft shadows, glowing backlight, gentle lens flare, "
        "warm dreamy palette",
        "golden hour: a low warm sun behind or beside the subject, long soft shadows, glowing "
        "edges and a warm, dreamy palette",
    ),
    Style(
        "noir",
        "moody low-key lighting, deep shadows, a single hard light source, high contrast, "
        "desaturated palette with one accent colour, wet reflective surfaces",
        "moody film noir: low-key light from a single hard source, deep shadows, high contrast, "
        "a muted palette with one accent colour, wet surfaces catching the light",
    ),
    Style(
        "neon",
        "night scene, glowing neon signs, cyan and magenta reflections on wet pavement, bokeh, "
        "cinematic cyberpunk mood",
        "a rainy night lit by neon: cyan and magenta glow reflected on wet ground, bokeh lights "
        "in the distance, a cinematic cyberpunk mood",
    ),
    Style(
        "product",
        "premium product photography, seamless backdrop, large softbox lighting with clean "
        "gradient reflections, precise focus, minimal composition",
        "a premium advertising product shot: seamless backdrop, large softboxes making clean "
        "gradient reflections, precise focus, generous negative space",
    ),
    Style(
        "architecture",
        "architectural photography, corrected vertical lines, clean geometry, natural daylight, "
        "wide-angle lens, minimal composition",
        "architectural photography: straight corrected verticals, strong clean geometry, natural "
        "daylight and a calm, minimal composition",
    ),
    Style(
        "fantasy",
        "epic fantasy concept art, painterly detail, volumetric god rays, sense of grand scale, "
        "rich saturated colour",
        "epic fantasy concept art: painterly detail, volumetric light shafts, a sense of vast "
        "scale and rich saturated colour",
    ),
    Style(
        "cartoon",
        "bold cartoon style, clean confident outlines, bright flat colours, expressive "
        "exaggerated shapes and faces, playful and readable",
        "a bold cartoon: clean confident outlines, bright flat colours, expressive exaggerated "
        "shapes and faces, playful and instantly readable",
    ),
    Style(
        "illustration",
        "hand-drawn digital illustration, confident linework, flat shapes with soft shading, "
        "harmonious limited palette, storybook charm",
        "a hand-drawn digital illustration in the manner of a picture book or editorial "
        "illustration: confident linework, flat shapes with soft shading, a limited harmonious "
        "palette and storybook charm",
    ),
    Style(
        "painting",
        "traditional oil painting on canvas, visible expressive brushstrokes, rich layered "
        "pigment, painterly light, gallery quality",
        "a traditional oil painting on canvas with visible, expressive brushstrokes, rich layered "
        "pigment and painterly light, like a work hanging in a gallery",
    ),
    Style(
        "graphic",
        "clean flat vector graphic design, bold simple shapes, crisp edges, balanced layout, "
        "solid background, precise legible typography",
        "clean flat graphic design such as a logo, icon or poster: bold simple vector shapes, "
        "crisp edges, a balanced layout on a plain background and precise, correctly spelled "
        "typography exactly as the user wrote it",
    ),
    Style(
        "anime",
        "high-quality anime illustration, clean line art, vibrant cel shading, expressive "
        "lighting, detailed background",
        "a high-quality anime illustration with clean line art, vibrant cel shading, expressive "
        "light and a detailed background",
    ),
    Style(
        "watercolor",
        "delicate watercolour painting, soft bleeding edges, visible paper texture, airy light "
        "palette",
        "a delicate watercolour painting with soft bleeding edges, visible paper texture and an "
        "airy, light palette",
    ),
    Style(
        "render3d",
        "stylized 3D render, soft global illumination, subsurface scattering, smooth tactile "
        "materials, playful vivid colour",
        "a stylized 3D render: soft global illumination, tactile materials with subsurface "
        "scattering and playful vivid colour",
    ),
)

_BY_ID = {s.id: s for s in STYLES}


def get_style(style_id: str | None) -> Style | None:
    return _BY_ID.get(style_id) if style_id else None


ENHANCE_SYSTEM = (
    "You write prompts for a high-end text-to-image model. Rewrite the user's idea as one "
    "vivid English prompt of 60 to 120 words, whatever language the idea is written in. "
    "Keep every subject, object, colour, count and piece of text the user asked for, exactly; "
    "never add people, animals or text they did not ask for. Make the picture captivating: "
    "choose a strong composition and camera angle, describe the light (direction, quality, "
    "time of day), the lens and depth of field, the colour palette, materials and textures, "
    "and the mood. Prefer concrete visual details over adjectives. Write plain descriptive "
    "sentences, no lists, no hashtags, no quality tags such as 4k, 8k or masterpiece. "
    "Output only the prompt."
)


def enhance_request(prompt: str, style: Style | None, *, has_references: bool) -> str:
    """The user message sent to the language model."""
    parts = [f"Idea: {prompt.strip()}"]
    if style:
        parts.append(f"Visual style to use: {style.direction}.")
    if has_references:
        parts.append(
            "The picture will also follow reference images the model can see; refer to them "
            "as 'the reference image' and do not describe their content in detail."
        )
    return "\n".join(parts)


# Photographic looks: with people in them, faces get the short realism clause.
PHOTO_LOOKS = frozenset(
    {"cinematic", "film", "portrait", "golden_hour", "noir", "neon", "product", "architecture"}
)


def apply_style(prompt: str, style: Style | None) -> str:
    """Prompt with the style's suffix, used when enhancement is off."""
    if not style:
        return prompt
    base = prompt.rstrip().rstrip(".")
    people = mentions_people(prompt)
    if people and style.people_suffix:
        return f"{base}. {style.people_suffix}."
    if people and style.id in PHOTO_LOOKS:
        return f"{base}. {style.suffix}, {PEOPLE_REALISM_SHORT}."
    return f"{base}. {style.suffix}."
