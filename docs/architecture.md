# Architecture

Photo is a local application: everything runs on the user's own machine and GPU.
Nothing leaves the machine except model downloads the user starts.

```
 Browser ── React + TypeScript (frontend/)
    │  REST /api/v1/*   +   WebSocket /api/v1/events
    ▼
 App server ── Python, FastAPI (backend/, package `photo`)
    │  job queue · history · image store · model manager · hardware profile
    │  HTTP + WebSocket on 127.0.0.1, random port, never exposed
    ▼
 Engine ── headless ComfyUI (engine/), PyTorch CUDA
```

## Why ComfyUI as the engine

ComfyUI supports new image models within days of release and has the most
mature VRAM management (offloading, FP8, NVFP4). Writing our own inference
stack would mean chasing every model release. Users never see ComfyUI: the app
server builds graphs from **our own versioned templates** (`backend/src/photo/engine/workflows/`)
and submits them through ComfyUI's API. User input only ever fills typed,
validated parameters; it can never inject nodes.

The engine is pinned to an exact release and its Python dependencies are locked
(`engine/pyproject.toml` + `engine/uv.lock`), so every install gets byte-identical
packages.

## Processes

| Process | Owner | Listens on |
|---|---|---|
| App server | user starts it (`photo serve`, launcher shortcut) | `127.0.0.1:7860` by default |
| Engine | spawned and supervised by the app server | `127.0.0.1:<random>` |

The app server restarts the engine if it crashes and fails the running job with
a readable error instead of hanging.

## Two virtual environments

The app server and the engine have separate environments. ComfyUI pulls heavy,
fast-moving dependencies (torch, transformers); keeping them out of the app
server means an engine update can never break the UI or the job store, and the
app server starts in under a second without importing torch.

## Jobs

All GPU work is a **job** persisted in SQLite (`data/photo.db`, WAL mode).

```
queued ──► running ──► succeeded
   │          ├──────► failed
   └──────────┴──────► cancelled
```

* One worker feeds the GPU; jobs run strictly in order.
* Progress, step previews and state changes are published on an in-process bus
  and fanned out to every connected browser over `/api/v1/events`.
* On startup, jobs left `running` by a crash are marked `failed` with reason
  `interrupted`; nothing silently disappears.

## Images

Results are written to `data/images/YYYY/MM/<id>.png`. Every PNG carries its full
generation parameters in a `photo` text chunk, so an image dragged back into
the app reproduces exactly — even after the database is lost. A WebP thumbnail
sits next to each image.

## Models

`backend/src/photo/catalog/models.toml` lists every supported model with exact
file URLs, sizes, SHA-256 hashes and licence. Each model has **variants** chosen
by GPU architecture and VRAM:

| GPU | Preferred precision |
|---|---|
| RTX 50 (Blackwell, sm_120) | NVFP4, falling back to FP8 / BF16 |
| RTX 40 (Ada, sm_89) | FP8 / BF16 |

Downloads resume after interruption, verify SHA-256 before a file is used, and
honour `HF_ENDPOINT` for regional mirrors.

## Security model

* Binds to `127.0.0.1` only. LAN access is opt-in and requires an access token.
* `Host` and `Origin` headers are validated to block DNS-rebinding and
  cross-site requests from other tabs.
* The engine is never reachable from outside the machine.
* No telemetry.

## Repository layout

```
backend/     app server (Python package `photo`, CLI, tests)
engine/      pinned ComfyUI dependency lock
frontend/    web UI
installer/   helper scripts used by install.ps1 / install.sh
docs/        documentation
```

Runtime state lives in git-ignored folders next to the code: `runtime/`
(uv, Python, engine), `data/` (database, images, logs) and `models/`.
