"""Command line: ``photo serve | setup | doctor | models``."""

from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from photo import __version__, prefs
from photo import setup as steps
from photo.catalog import default_catalog
from photo.config import LANGUAGES, Settings, is_loopback_host
from photo.downloads import DownloadError, DownloadRequest, download
from photo.hardware import detect_gpus, primary_gpu
from photo.model_manager import missing_files

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Photo — local AI image studio.")
models_app = typer.Typer(help="Manage models.")
app.add_typer(models_app, name="models")
console = Console()


def _settings() -> Settings:
    return Settings()


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Bind address. Default 127.0.0.1.")] = None,
    port: Annotated[int | None, typer.Option(help="Port. Default 7860.")] = None,
    open_browser: Annotated[bool, typer.Option("--open/--no-open")] = False,
) -> None:
    """Start Photo."""
    import uvicorn

    from photo.api.app import build_services, create_app
    from photo.logs import setup_logging

    overrides = {k: v for k, v in {"host": host, "port": port}.items() if v is not None}
    settings = Settings(**overrides)  # type: ignore[arg-type]
    setup_logging(settings.logs_dir)
    if not is_loopback_host(settings.host) and not settings.access_token:
        console.print(
            "[red]Refusing to listen on a network address without an access token.[/]\n"
            "Set PHOTO_ACCESS_TOKEN (or access_token in photo.toml) first."
        )
        raise typer.Exit(2)

    wildcard = settings.host in ("0.0.0.0", "::")  # noqa: S104 — only compared, never bound here
    url = f"http://{'127.0.0.1' if wildcard else settings.host}:{settings.port}"
    console.print(f"[bold]Photo {__version__}[/] → {url}")
    app_ = create_app(build_services(settings))
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(
        app_, host=settings.host, port=settings.port, log_level="warning", ws_ping_interval=20
    )


@app.command()
def doctor() -> None:
    """Check this machine and the installation."""
    settings = _settings()
    gpu = primary_gpu(detect_gpus())
    checks = steps.check_gpu(gpu)
    checks.append(steps.check_disk(settings, 25))
    commit = steps.installed_engine_commit(settings)
    pin = steps.engine_pin(settings)
    checks.append(steps.Check(
        "Engine", commit == pin.commit,
        f"{pin.version}" if commit == pin.commit else "not installed or outdated — run setup",
    ))  # fmt: skip
    if settings.engine_python.exists():
        try:
            checks.append(steps.Check("CUDA", True, steps.verify_engine_cuda(settings)))
        except steps.SetupError as exc:
            checks.append(steps.Check("CUDA", False, str(exc)))
    checks.append(steps.Check(
        "Web UI", (settings.frontend_dist / "index.html").exists(), str(settings.frontend_dist)
    ))  # fmt: skip

    table = Table(show_header=False, box=None)
    for c in checks:
        mark = "[green]✓[/]" if c.ok else ("[red]✗[/]" if c.fatal else "[yellow]![/]")
        table.add_row(mark, c.name, c.detail)
    console.print(table)
    if any(not c.ok and c.fatal for c in checks):
        raise typer.Exit(1)


def _progress() -> Progress:
    return Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )


async def _download_all(settings: Settings, reqs: list[tuple[str, DownloadRequest]]) -> None:
    with _progress() as bar:
        for label, req in reqs:
            task = bar.add_task(label, total=req.size)

            def advance(done: int, _total: int, task: TaskID = task) -> None:
                bar.update(task, completed=done)

            await download(req, advance)


@app.command()
def setup(
    models: Annotated[
        str, typer.Option(help="Models to install: 'recommended', 'none', or comma-separated ids.")
    ] = "recommended",
    skip_frontend: bool = False,
    ui: Annotated[
        bool, typer.Option("--ui", help="Open the setup wizard in the browser instead.")
    ] = False,
    language: Annotated[
        str | None, typer.Option(help=f"Interface language: {', '.join(LANGUAGES)}.")
    ] = None,
    models_dir: Annotated[Path | None, typer.Option(help="Where to store models.")] = None,
    data_dir: Annotated[
        Path | None, typer.Option(help="Where to store images and the database.")
    ] = None,
    engine_env_dir: Annotated[
        Path | None, typer.Option(help="Where to put the engine's Python environment.")
    ] = None,
) -> None:
    """Install or repair everything: engine, web UI and models. Safe to re-run."""
    if ui:
        _setup_wizard()
        return
    if language is not None and language not in LANGUAGES:
        console.print(
            f"[red]Unknown language {language!r}.[/] Choose one of: {', '.join(LANGUAGES)}"
        )
        raise typer.Exit(2)
    choices = {
        "language": language,
        "models_dir": models_dir.resolve() if models_dir else None,
        "data_dir": data_dir.resolve() if data_dir else None,
        "engine_env_dir": engine_env_dir.resolve() if engine_env_dir else None,
    }
    chosen = {k: v for k, v in choices.items() if v is not None}
    if chosen:
        prefs.update(chosen)
    settings = _settings()
    settings.ensure_dirs()
    gpu = primary_gpu(detect_gpus())

    console.rule("Checking system")
    fatal = False
    for c in steps.check_gpu(gpu):
        console.print(("[green]✓[/] " if c.ok else "[red]✗[/] ") + f"{c.name}: {c.detail}")
        fatal |= not c.ok and c.fatal
    if fatal:
        raise typer.Exit(1)

    try:
        console.rule("Engine")
        pin = steps.engine_pin(settings)
        if steps.installed_engine_commit(settings) != pin.commit:
            with tempfile.TemporaryDirectory(dir=settings.runtime) as tmp:
                archive = Path(tmp) / "engine.tar.gz"
                req = DownloadRequest(pin.url, archive, pin.size, pin.sha256)
                asyncio.run(_download_all(settings, [(f"ComfyUI {pin.version}", req)]))
                steps.install_engine_source(settings, archive)
        console.print(f"[green]✓[/] ComfyUI {pin.version}")
        steps.sync_engine_env(settings, steps.find_uv(settings))
        console.print(f"[green]✓[/] {steps.verify_engine_cuda(settings)}")

        if not skip_frontend:
            console.rule("Web UI")
            console.print(f"[green]✓[/] Web UI {steps.ensure_frontend(settings)}")

        console.rule("Models")
        _install_models(settings, gpu, models)
    except (steps.SetupError, DownloadError) as exc:
        console.print(f"\n[red]✗ {exc}[/]")
        raise typer.Exit(1) from None

    console.rule("Done")
    console.print("Start Photo with the desktop shortcut or `photo serve --open`.")


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _setup_wizard() -> None:
    """Serve the setup wizard and block until the user finishes it."""
    import uvicorn

    from photo.api.app import create_setup_app
    from photo.events import EventBus
    from photo.installer import SetupRunner
    from photo.logs import setup_logging

    settings = _settings()
    settings.ensure_dirs()
    setup_logging(settings.logs_dir)
    if _port_in_use("127.0.0.1", settings.port):
        console.print(
            f"[red]Port {settings.port} is in use.[/] If Photo is running, close it and run the "
            "installer again."
        )
        raise typer.Exit(1)
    try:
        steps.ensure_frontend(settings)
    except steps.SetupError as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1) from None

    bus = EventBus()
    runner = SetupRunner(settings, default_catalog(), bus, primary_gpu(detect_gpus()))
    servers: list[uvicorn.Server] = []

    def request_exit() -> None:
        servers[0].should_exit = True

    app_ = create_setup_app(settings, runner, bus, request_exit)
    server = uvicorn.Server(
        uvicorn.Config(app_, host="127.0.0.1", port=settings.port, log_level="warning")
    )
    servers.append(server)
    url = f"http://127.0.0.1:{settings.port}/setup"
    console.print(f"Setup is open in your browser: {url}")
    console.print("Keep this window open until setup finishes.")
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    server.run()
    if runner.state.status != "done":
        console.print("[yellow]Setup was closed before it finished.[/]")
        raise typer.Exit(1)


def _install_models(settings: Settings, gpu: object, selection: str) -> None:
    catalog = default_catalog()
    if selection == "none":
        return
    ids = [m.id for m in catalog.models[:1]] if selection == "recommended" else selection.split(",")
    reqs: list[tuple[str, DownloadRequest]] = []
    seen: set[str] = set()
    for model_id in ids:
        try:
            spec = catalog.get(model_id.strip())
        except KeyError:
            raise steps.SetupError(f"Unknown model {model_id!r}.") from None
        variant = spec.choose_variant(gpu)  # type: ignore[arg-type]
        console.print(f"{spec.name} → {variant.label}")
        for f in missing_files(settings, spec, variant):
            if f.name in seen:
                continue
            seen.add(f.name)
            reqs.append((f.name, DownloadRequest(
                f.url(settings.hf_endpoint), settings.models / f.relative_path,
                f.size, f.sha256, settings.hf_token,
            )))  # fmt: skip
    if reqs:
        total = sum(r.size for _, r in reqs)
        console.print(steps.check_disk(settings, total / 2**30 + 2).detail)
        asyncio.run(_download_all(settings, reqs))
    console.print("[green]✓[/] Models ready")


@models_app.command("list")
def models_list() -> None:
    """Show available models and what is installed."""
    settings = _settings()
    gpu = primary_gpu(detect_gpus())
    table = Table("Model", "Variant for this GPU", "Status", "Licence")
    for spec in default_catalog().models:
        v = spec.choose_variant(gpu)
        missing = missing_files(settings, spec, v)
        status = (
            "[green]installed[/]"
            if not missing
            else f"{sum(f.size for f in missing) / 2**30:.1f} GB to download"
        )
        table.add_row(f"{spec.name}\n[dim]{spec.id}[/]", v.label, status, spec.license)
    console.print(table)


@models_app.command("install")
def models_install(model_ids: list[str]) -> None:
    """Download models by id."""
    settings = _settings()
    try:
        _install_models(settings, primary_gpu(detect_gpus()), ",".join(model_ids))
    except (steps.SetupError, DownloadError) as exc:
        console.print(f"[red]✗ {exc}[/]")
        raise typer.Exit(1) from None


def _force_utf8_stdio() -> None:
    """Legacy Windows code pages (cp1251, cp437...) cannot encode ✓ and friends.

    Without this, the first status line crashes the installer on most non-English
    Windows machines whenever output is redirected.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
            reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _force_utf8_stdio()
    app()
