"""Curated looks and the prompt-enhancement instructions.

Style text is English on purpose: both image models follow English (and Chinese)
best, and the UI translates only the style *names*. Each style has two parts:

* ``suffix`` — appended to the prompt when enhancement is off;
* ``direction`` — handed to the language model when enhancement is on, so it can
  weave the look into the scene instead of bolting keywords onto the end.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Style:
    id: str
    suffix: str
    direction: str


STYLES: tuple[Style, ...] = (
    Style(
        "photo",
        "candid unretouched photograph, full-frame camera, natural available light, true-to-life "
        "colour, realistic textures and small everyday imperfections, subtle sensor grain",
        "a genuine, unretouched photograph a real person could have taken: name the camera and "
        "lens, use natural available light, and describe real-world texture (fabric weave, dust, "
        "wear, small imperfections) in an ordinary, uncurated setting. Keep the framing the idea "
        "implies. It must look like a real photo, never like a glossy, airbrushed render",
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


def apply_style(prompt: str, style: Style | None) -> str:
    """Prompt with the style's suffix, used when enhancement is off."""
    if not style:
        return prompt
    return f"{prompt.rstrip().rstrip('.')}. {style.suffix}."
