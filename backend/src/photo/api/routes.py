"""HTTP + WebSocket routes under ``/api/v1``."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import time
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from photo import __version__, prefs, storage
from photo.config import LANGUAGES
from photo.ids import is_valid_id, new_id
from photo.jobs import JobRejected
from photo.schemas import GenerateParams
from photo.styles import STYLES, get_style

if TYPE_CHECKING:
    from photo.api.app import Services

router = APIRouter()

_IMMUTABLE = {"Cache-Control": "private, max-age=31536000, immutable"}


def services(request: Request) -> Services:
    svc: Services = request.app.state.services
    return svc


Svc = Annotated["Services", Depends(services)]


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status, detail={"code": code, "message": message})


def _check_id(value: str) -> str:
    if not is_valid_id(value):
        raise _error(404, "not_found", "Not found")
    return value


# ---- system ------------------------------------------------------------------------


@router.get("/system")
async def system(svc: Svc) -> dict[str, Any]:
    gpu = svc.gpu
    return {
        "mode": "app",
        "version": __version__,
        "language": svc.language,
        "languages": list(LANGUAGES),
        "engine": {"state": svc.engine.state, "error": svc.engine.last_error},
        "gpu": None
        if gpu is None
        else {
            "name": gpu.name,
            "vram_gb": gpu.vram_gb,
            "arch": gpu.arch,
            "driver": gpu.driver,
            "supported": gpu.supported,
        },
        "models_dir": str(svc.settings.models),
    }


@router.post("/system/engine/restart", status_code=202)
async def restart_engine(svc: Svc) -> dict[str, str]:
    asyncio.create_task(svc.engine.restart())  # noqa: RUF006 — state is observable via /system
    return {"status": "restarting"}


class PreferencesBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str


@router.put("/preferences")
async def put_preferences(body: PreferencesBody, svc: Svc) -> dict[str, str]:
    """Persist the interface language so every device on the network gets it."""
    if body.language not in LANGUAGES:
        raise _error(422, "unsupported_language", f"Unsupported language {body.language!r}")
    prefs.update({"language": body.language})
    svc.language = body.language
    return {"language": svc.language}


# ---- looks and prompts -------------------------------------------------------------


@router.get("/styles")
async def list_styles() -> dict[str, Any]:
    return {"styles": [{"id": s.id, "suffix": s.suffix} for s in STYLES]}


class EnhanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    prompt: str = Field(min_length=1, max_length=4000)
    style: str | None = Field(default=None, max_length=32)
    has_references: bool = False


@router.post("/prompt/enhance")
async def enhance_prompt(body: EnhanceBody, svc: Svc) -> dict[str, str]:
    """Rewrite a prompt with the local language model, without generating an image."""
    try:
        text = await svc.jobs.enhance(body.prompt, get_style(body.style), body.has_references)
    except JobRejected as exc:
        raise _error(409, exc.code, exc.message) from None
    return {"prompt": text}


# ---- uploads -----------------------------------------------------------------------


@router.post("/uploads", status_code=201)
async def upload(svc: Svc, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
    """A picture to use as a reference or variation source. Identical files dedupe."""
    raw = await file.read(storage.MAX_UPLOAD_BYTES + 1)
    digest = hashlib.sha256(raw).hexdigest()
    row = svc.db.one("SELECT * FROM uploads WHERE sha256=?", (digest,))
    if row is None:
        upload_id = new_id()
        try:
            stored = await asyncio.to_thread(
                storage.save_upload, svc.settings.uploads_dir, upload_id, raw
            )
        except storage.InvalidImageError as exc:
            raise _error(415, "invalid_image", str(exc)) from None
        svc.db.execute(
            "INSERT INTO uploads (id, sha256, path, thumb_path, width, height, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (upload_id, digest, stored.path, stored.thumb_path, stored.width, stored.height,
             time.time()),
        )  # fmt: skip
        row = svc.db.one("SELECT * FROM uploads WHERE id=?", (upload_id,))
    assert row is not None
    return {"id": row["id"], "width": row["width"], "height": row["height"]}


def _upload_row(svc: Services, upload_id: str) -> Any:
    row = svc.db.one("SELECT * FROM uploads WHERE id=?", (_check_id(upload_id),))
    if row is None:
        raise _error(404, "not_found", "Upload not found")
    return row


@router.get("/uploads/{upload_id}/thumb")
async def upload_thumb(upload_id: str, svc: Svc) -> FileResponse:
    row = _upload_row(svc, upload_id)
    path = storage.resolve(svc.settings.uploads_dir, row["thumb_path"])
    return FileResponse(path, media_type="image/webp", headers=_IMMUTABLE)


@router.get("/uploads/{upload_id}/file")
async def upload_file(upload_id: str, svc: Svc) -> FileResponse:
    row = _upload_row(svc, upload_id)
    path = storage.resolve(svc.settings.uploads_dir, row["path"])
    return FileResponse(path, media_type="image/png", headers=_IMMUTABLE)


# ---- models ------------------------------------------------------------------------


class InstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant: str | None = None


@router.get("/models")
async def list_models(svc: Svc) -> dict[str, Any]:
    return {"models": [svc.models.describe(m) for m in svc.catalog.models]}


@router.post("/models/{model_id}/install", status_code=202)
async def install_model(model_id: str, svc: Svc, body: InstallBody | None = None) -> dict[str, Any]:
    try:
        task = svc.models.install(model_id, body.variant if body else None)
    except KeyError as exc:
        raise _error(404, "not_found", f"Unknown model or variant: {exc}") from None
    return task.to_api()


@router.delete("/models/{model_id}/install", status_code=204)
async def cancel_install(model_id: str, svc: Svc) -> None:
    await svc.models.cancel(model_id)


# ---- jobs --------------------------------------------------------------------------


@router.post("/jobs", status_code=202)
async def create_job(params: GenerateParams, svc: Svc) -> dict[str, Any]:
    try:
        job = svc.jobs.submit(params)
    except JobRejected as exc:
        raise _error(409, exc.code, exc.message) from None
    return job.to_api()


@router.get("/jobs")
async def list_jobs(
    svc: Svc,
    active: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    return {"jobs": [j.to_api() for j in svc.jobs.list_jobs(limit, active_only=active)]}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str, svc: Svc) -> dict[str, Any]:
    job = svc.jobs.get(_check_id(job_id))
    if job is None:
        raise _error(404, "not_found", "Job not found")
    return job.to_api()


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, svc: Svc) -> dict[str, Any]:
    job = await svc.jobs.cancel(_check_id(job_id))
    if job is None:
        raise _error(404, "not_found", "Job not found")
    return job.to_api()


# ---- images ------------------------------------------------------------------------


def _image_api(row: Any) -> dict[str, Any]:
    meta = json.loads(row["params"])
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "width": row["width"],
        "height": row["height"],
        "seed": row["seed"],
        "model": row["model"],
        "favorite": bool(row["favorite"]),
        "created_at": row["created_at"],
        "params": meta.get("params", {}),
        "steps": meta.get("steps"),
        "cfg": meta.get("cfg"),
        "final_prompt": meta.get("final_prompt"),
    }


@router.get("/images")
async def list_images(
    svc: Svc,
    before: str | None = None,
    favorites: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> dict[str, Any]:
    clauses, args = ["deleted_at IS NULL"], []
    if before:
        clauses.append("id < ?")
        args.append(_check_id(before))
    if favorites:
        clauses.append("favorite = 1")
    rows = svc.db.all(
        f"SELECT * FROM images WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",  # noqa: S608
        (*args, limit + 1),
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "images": [_image_api(r) for r in rows],
        "next": rows[-1]["id"] if has_more and rows else None,
    }


def _image_row(svc: Services, image_id: str) -> Any:
    row = svc.db.one(
        "SELECT * FROM images WHERE id=? AND deleted_at IS NULL", (_check_id(image_id),)
    )
    if row is None:
        raise _error(404, "not_found", "Image not found")
    return row


@router.get("/images/{image_id}")
async def get_image(image_id: str, svc: Svc) -> dict[str, Any]:
    return _image_api(_image_row(svc, image_id))


@router.get("/images/{image_id}/file")
async def image_file(image_id: str, svc: Svc, download: bool = False) -> FileResponse:
    row = _image_row(svc, image_id)
    path = storage.resolve(svc.settings.images_dir, row["path"])
    return FileResponse(
        path,
        media_type="image/png",
        headers=_IMMUTABLE,
        filename=f"photo-{row['id']}.png" if download else None,
    )


@router.get("/images/{image_id}/thumb")
async def image_thumb(image_id: str, svc: Svc) -> FileResponse:
    row = _image_row(svc, image_id)
    path = storage.resolve(svc.settings.images_dir, row["thumb_path"])
    return FileResponse(path, media_type="image/webp", headers=_IMMUTABLE)


class ImagePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    favorite: bool | None = None


@router.patch("/images/{image_id}")
async def patch_image(image_id: str, body: ImagePatch, svc: Svc) -> dict[str, Any]:
    _image_row(svc, image_id)
    if body.favorite is not None:
        svc.db.execute("UPDATE images SET favorite=? WHERE id=?", (int(body.favorite), image_id))
    return _image_api(_image_row(svc, image_id))


@router.delete("/images/{image_id}", status_code=204)
async def delete_image(image_id: str, svc: Svc) -> None:
    """Moves the image to the trash; files stay on disk until the trash is emptied."""
    _image_row(svc, image_id)
    svc.db.execute("UPDATE images SET deleted_at=? WHERE id=?", (time.time(), image_id))
    svc.bus.publish("image_deleted", {"image_id": image_id})


@router.post("/images/{image_id}/restore")
async def restore_image(image_id: str, svc: Svc) -> dict[str, Any]:
    svc.db.execute("UPDATE images SET deleted_at=NULL WHERE id=?", (_check_id(image_id),))
    return _image_api(_image_row(svc, image_id))


# ---- events ------------------------------------------------------------------------


@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    svc: Services = ws.app.state.services
    await ws.accept()
    async with svc.bus.subscribe() as queue:
        # Snapshot first so a freshly opened tab is immediately consistent.
        await ws.send_text(json.dumps({
            "type": "hello",
            "version": __version__,
            "engine": {"state": svc.engine.state, "error": svc.engine.last_error},
            "jobs": [j.to_api() for j in svc.jobs.list_jobs(50, active_only=True)],
        }))  # fmt: skip

        async def pump() -> None:
            while True:
                frame = await queue.get()
                if frame.text is not None:
                    await ws.send_text(frame.text)
                elif frame.data is not None:
                    await ws.send_bytes(frame.data)

        sender = asyncio.create_task(pump())
        try:
            while True:  # we only read to notice disconnects; clients send pings
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender
