# Roadmap

Ordered by what unlocks the most for users. Each milestone ships only after an
end-to-end run on both an RTX 40 and an RTX 50 card.

## 0.1 — Generate (current)

- [x] One-click install on Windows and Linux, pinned and hash-verified
- [x] Engine supervision, job queue, live previews, gallery
- [x] Z-Image Turbo, NVFP4/BF16 variant selection
- [x] Setup wizard: language, per-drive storage choice, models, live progress
- [x] 12 interface languages, right-to-left support
- [x] Release packages with the prebuilt UI built by CI (on tag)
- [ ] End-to-end test on RTX 40

## 0.2 — Edit

- [x] Selection editor: brush, rectangle, lasso, erase, invert, undo
- [x] Instruction editing, whole picture or inside a selection (FLUX.2 Klein)
- [x] Remove objects; hide faces and plates (blur, pixelate, cover — no AI)
- [x] Crop-and-stitch with bounded feathering: pixels outside are untouched
- [x] Chained versions with hold-to-compare and step back
- [ ] Zoom and pan in the editor for precise selections on large photos
- [ ] Outpaint: extend the picture beyond its edges
- [ ] Click-to-select objects (SAM 2) and automatic face finding for "hide"
- [ ] Qwen-Image-Edit as a second, heavier editing model (compare first)

## 0.3 — Finish

- Upscale ×2/×4 with detail (SeedVR2 / tiled diffusion)
- Background removal (BiRefNet), face restoration
- Drag a PNG in to restore its exact settings
- Batch processing of folders

## 0.4 — Control

- Structure control: pose, depth, edges
- Style and subject reference images
- LoRA library: import, preview, strength per prompt
- Optional local prompt helper (small LLM, off by default)

## Later

- More models as they are released and verified (FLUX family, Qwen-Image, …)
- Multi-GPU queue
- LoRA training
