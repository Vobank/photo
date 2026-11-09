# Automatic mode

With **Model: Auto** and **Style: Auto** (the defaults) the user only describes the
picture. Photo then:

1. **Reads the request** with the local Qwen3-4B language model (already on disk as
   the text encoder, so nothing extra is downloaded). One greedy pass, 1–4 s,
   answers `MEDIUM | English prompt`. Greedy decoding means the same request is
   always routed the same way, so a fixed seed reproduces the same picture.
2. **Applies the recipe for that medium** (`styles.py`): photo, anime, cartoon,
   illustration, painting, watercolor, render3d or graphic.
3. **Picks the model that is best at that medium** among the installed ones that
   can do what the request needs (`auto.MODEL_PREFERENCE`).

The request itself is stored unchanged (`"auto"` stays `"auto"`), so *Use these
settings* decides afresh; what was decided is stored next to it as `resolved` and
shown under the picture ("Auto: Photoreal · FLUX.2 Klein 4B").

If the language model is missing or answers something unusable, the job still
runs: medium photo, the user's original words.

## Why these choices

Side-by-side runs on an RTX 5080, same seed, prompts written in Russian:

| Finding | Consequence |
|---|---|
| Untranslated Russian was misread: "робот-повар" became a human chef on Klein, "ёжик" a squirrel on Z-Image. Translated, both were right. | Always translate in auto mode. |
| Klein photos look like real, unstaged snapshots and keep the requested framing; Z-Image looks glossier and drifts to tight close-ups and East-Asian faces for neutral prompts. | `photo` → Klein first. |
| Klein is clearly better at oil painting, children's illustration, watercolour and anime detail. | Drawn and painted media → Klein first. |
| Z-Image makes real logos, badges and stickers with correct lettering; Klein tends to set plain text. Z-Image also makes cleaner toy-like 3D. | `graphic`, `render3d` → Z-Image first. |
| The first photo recipe ("skin pores, hair strands") pushed Z-Image into extreme face close-ups even for street scenes. | The recipe describes realism without dictating framing. |
| Full prompt expansion ("Improve the prompt") adds 25–50 s. | Kept optional; auto mode only classifies and translates. |
| A 4B model mislabels some requests ("наклейка" → "sticky note", watercolour). Six short examples in the instruction fixed every case in the test set. | Few-shot examples in `CLASSIFY_SYSTEM`; test any change against `tests/test_gpu_e2e.py`. |

## Changing the routing

Edit `MODEL_PREFERENCE` only with new side-by-side evidence, add the new case to
`test_auto_mode_routes_by_what_was_asked`, and run `uv run pytest -m gpu -s`.
