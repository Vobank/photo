# Photo

A local studio for generating and editing images with open models, on your own
NVIDIA RTX GPU. No account, no cloud, no telemetry: prompts and pictures never
leave your computer.

[Русская версия](README.ru.md)

## What it does today

- Text-to-image with **Z-Image Turbo** (Apache-2.0, commercial use allowed),
  8 steps: about 2.7 s for a 1024×1024 image on an RTX 5080 (first image
  after start ~24 s while the model loads).
- Live step previews, a queue you can keep adding to, and cancellation.
- Gallery with favourites and undoable delete. Every PNG carries its exact
  parameters (the standard `parameters` text field plus full JSON).
- Model variants picked for your card automatically: NVFP4 on RTX 50, BF16 on RTX 40.
- English and Russian interface; dark, light or system theme; works from a phone
  on your home network (opt-in, token protected).

Editing (inpainting, instruction edits, upscaling, background removal) is next —
see [the roadmap](docs/roadmap.md).

## Requirements

| | Minimum | Recommended |
|---|---|---|
| GPU | NVIDIA RTX 40 series, 8 GB | RTX 4080 / 50 series, 16 GB+ |
| Driver | 580 or newer | latest |
| RAM | 16 GB | 32 GB |
| Disk | 25 GB free | 100 GB+ for several models |
| OS | Windows 10 1903+ x64, or Linux x86_64 | Windows 11 |

## Install

**Windows** — download the release zip (or `git clone`), unpack it to a short path
such as `C:\Photo`, and double-click **`install.cmd`**.

**Linux**

```sh
./install.sh
```

The installer checks your GPU and driver, sets up a private Python environment,
installs the engine with pinned, hash-verified packages, and downloads the
recommended model (~10 GB). Nothing is installed system-wide; delete the folder
to uninstall. Re-running the installer repairs a broken install.

Then start **Photo** from the desktop shortcut, `Photo.cmd`, or `./photo.sh`.
It opens at <http://127.0.0.1:7860>.

Behind a slow or blocked connection to Hugging Face, set a mirror before
installing: `set PHOTO_HF_ENDPOINT=https://hf-mirror.com`.

## How it works

A small Python server (FastAPI) owns the job queue, gallery and model files and
drives a headless [ComfyUI](https://github.com/Comfy-Org/ComfyUI) engine that it
starts and supervises. The web UI is React. Details in
[docs/architecture.md](docs/architecture.md).

## Development

```sh
cd backend && uv sync && uv run pytest     # server
cd frontend && npm ci && npm run dev       # UI on :5173, proxies the API to :7860
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

Photo is Apache-2.0. Each model has its own licence, shown on the Models page;
what you may do with generated images depends on the model you used.
