"""FastAPI application factory and lifecycle."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from photo import __version__
from photo.api import routes
from photo.api.security import GuardMiddleware
from photo.catalog import Catalog, default_catalog
from photo.config import Settings
from photo.db import Database
from photo.engine.process import EngineProcess
from photo.events import EventBus
from photo.hardware import Gpu, detect_gpus, primary_gpu
from photo.jobs import JobService
from photo.model_manager import ModelManager

log = logging.getLogger(__name__)


@dataclass
class Services:
    settings: Settings
    catalog: Catalog
    gpus: list[Gpu]
    gpu: Gpu | None
    db: Database
    bus: EventBus
    engine: EngineProcess
    jobs: JobService
    models: ModelManager


def build_services(
    settings: Settings,
    *,
    gpus: list[Gpu] | None = None,
    catalog: Catalog | None = None,
    engine: EngineProcess | None = None,
) -> Services:
    settings.ensure_dirs()
    gpus = detect_gpus() if gpus is None else gpus
    gpu = primary_gpu(gpus)
    catalog = catalog or default_catalog()
    db = Database(settings.database_path)
    bus = EventBus()
    engine = engine or EngineProcess(settings, gpu)
    engine.on_state_change = lambda state, error: bus.publish(
        "engine", {"state": state, "error": error}
    )
    return Services(
        settings=settings,
        catalog=catalog,
        gpus=gpus,
        gpu=gpu,
        db=db,
        bus=bus,
        engine=engine,
        jobs=JobService(db, settings, catalog, engine, bus, gpu),
        models=ModelManager(settings, catalog, bus, gpu),
    )


def create_app(services: Services, *, start_engine: bool = True) -> FastAPI:
    settings = services.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        recovered = services.jobs.recover()
        if recovered:
            log.warning("marked %d interrupted job(s) as failed", recovered)
        if start_engine:
            await services.engine.start()
        services.jobs.start()
        try:
            yield
        finally:
            await services.jobs.stop()
            await services.engine.stop()
            services.db.close()

    app = FastAPI(
        title="Photo",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.services = services
    app.add_middleware(
        GuardMiddleware,
        allowed_hosts=settings.allowed_hosts,
        access_token=settings.access_token,
    )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            body = {"error": detail}
        else:
            body = {"error": {"code": f"http_{exc.status_code}", "message": str(detail)}}
        return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": {"code": "invalid_request", "message": "Invalid request", "fields": fields}},
            status_code=422,
        )

    app.include_router(routes.router, prefix="/api/v1")
    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist.resolve()
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False, response_model=None)
    async def spa(path: str) -> FileResponse | JSONResponse:
        if path.startswith("api/"):
            return JSONResponse(
                {"error": {"code": "not_found", "message": "Unknown API route"}}, status_code=404
            )
        if not index.exists():
            return JSONResponse(
                {"error": {"code": "frontend_missing", "message": "The web UI is not built."}},
                status_code=503,
            )
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            # Vite fingerprints everything under assets/, so it can be cached forever.
            immutable = candidate.parent.name == "assets"
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if immutable else {}
            return FileResponse(candidate, headers=headers)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
