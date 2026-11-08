import time

from fastapi.testclient import TestClient

from photo.api.app import Services

from .conftest import install_fake_model

GEN = {"model": "z-image-turbo", "prompt": "a lighthouse at dusk", "width": 768, "height": 512}


def wait_for(client: TestClient, job_id: str, status: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/v1/jobs/{job_id}").json()
        if job["status"] == status:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job stayed {job['status']}, wanted {status}: {job}")


def test_system_reports_gpu(client: TestClient) -> None:
    body = client.get("/api/v1/system").json()
    assert body["gpu"]["arch"] == "blackwell"
    assert body["engine"]["state"] == "ready"


def test_models_list_marks_recommended_variant(client: TestClient) -> None:
    (model,) = client.get("/api/v1/models").json()["models"]
    assert model["installed"] is False
    rec = [v for v in model["variants"] if v["recommended"]]
    assert [v["id"] for v in rec] == ["nvfp4"]
    assert rec[0]["download_bytes"] == 3 * 16


def test_job_rejected_when_model_missing(client: TestClient) -> None:
    r = client.post("/api/v1/jobs", json=GEN)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "model_not_installed"


def test_validation_errors_are_structured(client: TestClient) -> None:
    r = client.post("/api/v1/jobs", json={**GEN, "width": 777, "bogus": 1})
    assert r.status_code == 422
    fields = {f["field"] for f in r.json()["error"]["fields"]}
    assert {"width", "bogus"} <= fields


def test_generate_end_to_end(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    job = client.post("/api/v1/jobs", json={**GEN, "batch_size": 2, "seed": 123}).json()
    assert job["status"] == "queued" and job["seed"] == 123

    done = wait_for(client, job["id"], "succeeded")
    assert done["progress"] == 1
    assert len(done["image_ids"]) == 2

    graph = services.engine.client.graphs[0]  # type: ignore[attr-defined]
    assert any(n["inputs"].get("text") == GEN["prompt"] for n in graph.values())

    images = client.get("/api/v1/images").json()["images"]
    assert {i["id"] for i in images} == set(done["image_ids"])
    img = images[0]
    assert img["params"]["prompt"] == GEN["prompt"] and img["seed"] == 123

    f = client.get(f"/api/v1/images/{img['id']}/file")
    assert f.status_code == 200 and f.headers["content-type"] == "image/png"
    assert "immutable" in f.headers["cache-control"]
    assert client.get(f"/api/v1/images/{img['id']}/thumb").headers["content-type"] == "image/webp"


def test_random_seed_assigned_and_js_safe(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    job = client.post("/api/v1/jobs", json=GEN).json()
    assert 0 <= job["seed"] <= 2**53 - 1


def test_favorite_delete_restore(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    job = client.post("/api/v1/jobs", json=GEN).json()
    image_id = wait_for(client, job["id"], "succeeded")["image_ids"][0]

    assert client.patch(f"/api/v1/images/{image_id}", json={"favorite": True}).json()["favorite"]
    assert len(client.get("/api/v1/images?favorites=true").json()["images"]) == 1

    assert client.delete(f"/api/v1/images/{image_id}").status_code == 204
    assert client.get(f"/api/v1/images/{image_id}").status_code == 404
    assert client.post(f"/api/v1/images/{image_id}/restore").status_code == 200


def test_cancel_running_job(client: TestClient, services: Services) -> None:
    import asyncio

    install_fake_model(services)
    fake = services.engine.client  # type: ignore[attr-defined]
    fake.block = asyncio.Event()
    job = client.post("/api/v1/jobs", json=GEN).json()
    wait_for(client, job["id"], "running")
    client.post(f"/api/v1/jobs/{job['id']}/cancel")
    assert wait_for(client, job["id"], "cancelled")["error"] is None


def test_engine_oom_becomes_friendly_error(client: TestClient, services: Services) -> None:
    from photo.engine.client import EngineError

    install_fake_model(services)
    services.engine.client.fail_with = EngineError("CUDA error: out of memory")  # type: ignore[attr-defined]
    job = client.post("/api/v1/jobs", json=GEN).json()
    failed = wait_for(client, job["id"], "failed")
    assert "video memory" in failed["error"]


def test_pagination(client: TestClient, services: Services) -> None:
    install_fake_model(services)
    job = client.post("/api/v1/jobs", json={**GEN, "batch_size": 3}).json()
    wait_for(client, job["id"], "succeeded")
    page1 = client.get("/api/v1/images?limit=2").json()
    assert len(page1["images"]) == 2 and page1["next"]
    page2 = client.get(f"/api/v1/images?limit=2&before={page1['next']}").json()
    assert len(page2["images"]) == 1 and page2["next"] is None


def test_events_socket_sends_snapshot_then_job_events(
    client: TestClient, services: Services
) -> None:
    install_fake_model(services)
    with client.websocket_connect("ws://127.0.0.1:7860/api/v1/events") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/v1/jobs", json=GEN)
        kinds = set()
        for _ in range(12):
            msg = ws.receive()
            if msg.get("text"):
                import json

                kinds.add(json.loads(msg["text"])["type"])
            if "image" in kinds:
                break
        assert {"job", "image"} <= kinds


def test_unknown_api_route_is_json_404(client: TestClient) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] in {"not_found", "http_404"}


def test_bad_ids_never_touch_the_db(client: TestClient) -> None:
    assert client.get("/api/v1/images/..%2F..%2Fetc/file").status_code == 404
    assert client.get("/api/v1/jobs/' OR 1=1 --").status_code == 404
