from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from photo.api.app import build_services, create_app
from photo.config import Settings

from .conftest import RTX_5080, FakeEngine


def make(
    settings: Settings, client_ip: str = "127.0.0.1", host: str = "127.0.0.1:7860"
) -> TestClient:
    svc = build_services(settings, gpus=[RTX_5080], engine=FakeEngine())  # type: ignore[arg-type]
    return TestClient(
        create_app(svc, start_engine=False), base_url=f"http://{host}", client=(client_ip, 5000)
    )


@pytest.fixture
def local(settings: Settings) -> Iterator[TestClient]:
    with make(settings) as c:
        yield c


def test_dns_rebinding_host_blocked(settings: Settings) -> None:
    with make(settings, host="evil.example:7860") as c:
        r = c.get("/api/v1/system")
    assert r.status_code == 421


def test_localhost_names_allowed(settings: Settings) -> None:
    for host in ("localhost:7860", "127.0.0.1:7860", "[::1]:7860"):
        with make(settings, host=host) as c:
            assert c.get("/api/v1/system").status_code == 200, host


def test_cross_site_post_blocked(local: TestClient) -> None:
    r = local.post("/api/v1/jobs", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_post_allowed(local: TestClient) -> None:
    r = local.post("/api/v1/jobs", json={}, headers={"Origin": "http://127.0.0.1:7860"})
    assert r.status_code == 422  # reached validation, not blocked


def test_cross_site_websocket_blocked(local: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    with (
        pytest.raises(WebSocketDisconnect),
        local.websocket_connect(
            "ws://127.0.0.1:7860/api/v1/events", headers={"Origin": "https://evil.example"}
        ),
    ):
        pass


def test_lan_client_needs_token(tmp_path) -> None:  # type: ignore[no-untyped-def]
    s = Settings(home=tmp_path, allowed_hosts=("photo.lan",), access_token="s3cret-token")
    with make(s, client_ip="192.168.1.20", host="photo.lan:7860") as c:
        assert c.get("/api/v1/system").status_code == 401
        assert c.get("/api/v1/system", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = c.get("/api/v1/system", headers={"Authorization": "Bearer s3cret-token"})
        assert ok.status_code == 200
        c.cookies.set("photo_token", "s3cret-token")
        assert c.get("/api/v1/system").status_code == 200


def test_lan_client_rejected_without_configured_token(settings: Settings) -> None:
    with make(settings, client_ip="192.168.1.20") as c:
        assert c.get("/api/v1/system").status_code == 401
