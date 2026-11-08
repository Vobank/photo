# Contributing

Thanks for helping. A few rules keep Photo reliable for everyone who installs it.

## Setup

```sh
# server (Python 3.13, uv)
cd backend
uv sync
uv run pytest

# engine (needs an NVIDIA GPU)
uv run photo setup --models none

# UI (Node 22+)
cd frontend
npm ci
npm run dev        # http://127.0.0.1:5173, API proxied to the running server
```

## Before you open a pull request

```sh
cd backend  && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest
cd frontend && npm run lint && npm run typecheck && npm test -- --run && npm run build
```

CI runs the same checks on Windows and Linux.

## Ground rules

- **Small, focused commits** with a message that says why, not just what.
- **No network calls** other than downloads the user starts. No telemetry, ever.
- **Pin everything.** New engine packages go through `engine/uv.lock`; new model
  files go in `models.toml` with revision, size and SHA-256.
- **Every user-facing string is translated.** Add keys to both `en.json` and
  `ru.json`; a test fails if they diverge.
- **User input never shapes a graph.** Prompts fill typed parameters of graphs
  built in `engine/pipelines.py`.
- Adding a model: include its licence, set `commercial_use` honestly, and test it
  on both RTX 40 and RTX 50 if the variant applies to both.

## Reporting bugs

Attach `data/logs/photo.log` and `data/logs/engine.log` and the output of
`photo doctor`. For security issues, see [SECURITY.md](SECURITY.md).
