# Roadmap

Ordered by what unlocks the most for users. Each milestone ships only after an
end-to-end run on both an RTX 40 and an RTX 50 card.

## 0.1 — Generate (current)

- [x] One-click install on Windows and Linux, pinned and hash-verified
- [x] Engine supervision, job queue, live previews, gallery
- [x] Z-Image Turbo, NVFP4/BF16 variant selection
- [ ] Release packages with the prebuilt UI attached by CI
- [ ] End-to-end test on RTX 40

## 0.2 — Edit

- Canvas editor: brush and lasso masks, undo history, zoom/pan
- Instruction editing ("make it night", "remove the person") with Qwen-Image-Edit
- Inpaint / outpaint with mask feathering and automatic crop-and-stitch
- Click-to-select objects (SAM 2)
- Before/after compare slider

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
