"""Automatic mode: classification parsing, routing, and the job flow end to end."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from photo.api.app import Services
from photo.auto import MEDIA, MODEL_PREFERENCE, parse_classification, route
from photo.engine.pipelines import build_classify

from .conftest import install_fake_model
from .test_api import wait_for

AUTO = {"model": "auto", "style": "auto", "width": 768, "height": 768}


# ---- parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("answer", "medium", "prompt"),
    [
        ("anime | a girl wizard with a cat", "anime", "a girl wizard with a cat"),
        (
            'Logo | coffee shop logo with the text "BEAN"',
            "graphic",
            'coffee shop logo with the text "BEAN"',
        ),
        ("3D | a cute robot chef", "render3d", "a cute robot chef"),
        ("stickers | stickers with a kitten", "graphic", "stickers with a kitten"),
        ("photos | a cat on a windowsill", "photo", "a cat on a windowsill"),
        ("poster for a movie about space", "graphic", "poster for a movie about space"),
        (
            "Here you go:\nwatercolour | a lighthouse in a storm",
            "watercolor",
            "a lighthouse in a storm",
        ),
        ('photo | "an old fisherman mending a net"', "photo", "an old fisherman mending a net"),
    ],
)
def test_parse_understood(answer: str, medium: str, prompt: str) -> None:
    c = parse_classification(answer, "запрос пользователя")
    assert (c.medium, c.prompt, c.understood) == (medium, prompt, True)


@pytest.mark.parametrize(
    "answer",
    ["", "I cannot help with that.", "sculpture | a bust", "photo |", "photo | a"],
)
def test_parse_falls_back_to_photo_and_original(answer: str) -> None:
    original = "пожилой рыбак чинит сеть на причале"
    c = parse_classification(answer, original)
    assert c.understood is False
    assert c.prompt == original
    assert c.medium in MEDIA


def test_classify_graph_is_greedy_and_small() -> None:
    api = build_classify("qwen.safetensors", "кот").graph.to_api()
    gen = next(n["inputs"] for n in api.values() if n["class_type"] == "TextGenerateV2")
    assert gen["sampling_mode"] == "off"  # same request → same route → seeds reproduce
    assert gen["prompt"] == "кот"
    assert gen["max_length"] <= 200


# ---- routing -------------------------------------------------------------------------


def test_every_medium_has_a_route() -> None:
    assert set(MODEL_PREFERENCE) == set(MEDIA)


def test_route_prefers_and_falls_back() -> None:
    both = ["z-image-turbo", "flux2-klein-4b"]
    assert route("photo", both) == "flux2-klein-4b"
    assert route("graphic", both) == "z-image-turbo"
    assert route("photo", ["z-image-turbo"]) == "z-image-turbo"
    assert route("photo", []) is None


# ---- job flow ------------------------------------------------------------------------


def _install_both(services: Services) -> None:
    install_fake_model(services, "z-image-turbo", "nvfp4")
    install_fake_model(services, "flux2-klein-4b", "nvfp4")


def _graph_prompt(graph: dict) -> str:
    texts = [n["inputs"]["text"] for n in graph.values() if n["class_type"] == "CLIPTextEncode"]
    return texts[0]


def test_logo_request_goes_to_z_image_with_graphic_recipe(
    client: TestClient, services: Services
) -> None:
    _install_both(services)
    fake = services.engine.client  # type: ignore[attr-defined]
    fake.classify_answer = 'graphic | a coffee shop logo with the text "BEAN"'
    job = client.post("/api/v1/jobs", json={**AUTO, "prompt": 'логотип кофейни "BEAN"'}).json()
    done = wait_for(client, job["id"], "succeeded")

    assert done["model"] == "z-image-turbo"
    assert done["resolved"]["medium"] == "graphic"
    assert done["resolved"]["style"] == "graphic"
    image_prompt = _graph_prompt(fake.graphs[-1])
    assert image_prompt.startswith('a coffee shop logo with the text "BEAN"')
    assert "vector" in image_prompt  # the graphic recipe was applied

    image = client.get(f"/api/v1/images/{done['image_ids'][0]}").json()
    # The request is kept as made, so "use these settings" decides afresh next time.
    assert image["params"]["model"] == "auto" and image["params"]["style"] == "auto"
    assert image["params"]["prompt"] == 'логотип кофейни "BEAN"'
    assert image["resolved"]["model"] == "z-image-turbo"
    assert image["model"] == "z-image-turbo"


def test_photo_request_goes_to_klein_with_photo_recipe(
    client: TestClient, services: Services
) -> None:
    _install_both(services)
    fake = services.engine.client  # type: ignore[attr-defined]
    fake.classify_answer = "photo | an old fisherman mending a net on a pier at dawn"
    job = client.post("/api/v1/jobs", json={**AUTO, "prompt": "рыбак чинит сеть"}).json()
    done = wait_for(client, job["id"], "succeeded")
    assert done["model"] == "flux2-klein-4b"
    assert "unretouched photograph" in _graph_prompt(fake.graphs[-1])


def test_only_installed_models_are_used(client: TestClient, services: Services) -> None:
    install_fake_model(services, "z-image-turbo", "nvfp4")
    done = wait_for(
        client,
        client.post("/api/v1/jobs", json={**AUTO, "prompt": "кот"}).json()["id"],
        "succeeded",
    )
    assert done["model"] == "z-image-turbo"


def test_unusable_answer_keeps_the_users_words(client: TestClient, services: Services) -> None:
    _install_both(services)
    fake = services.engine.client  # type: ignore[attr-defined]
    fake.classify_answer = "Sorry, I can't."
    done = wait_for(
        client,
        client.post("/api/v1/jobs", json={**AUTO, "prompt": "кот на подоконнике"}).json()["id"],
        "succeeded",
    )
    assert done["resolved"]["medium"] == "photo"
    assert done["resolved"]["prompt"] is None
    assert _graph_prompt(fake.graphs[-1]).startswith("кот на подоконнике")


def test_explicit_style_routes_without_asking_the_language_model(
    client: TestClient, services: Services
) -> None:
    _install_both(services)
    fake = services.engine.client  # type: ignore[attr-defined]
    done = wait_for(
        client,
        client.post("/api/v1/jobs", json={**AUTO, "style": "watercolor", "prompt": "маяк"}).json()[
            "id"
        ],
        "succeeded",
    )
    assert done["model"] == "flux2-klein-4b"
    assert len(fake.graphs) == 1  # no classification run


def test_detail_pass_is_best_effort_in_auto(client: TestClient, services: Services) -> None:
    _install_both(services)
    r = client.post("/api/v1/jobs", json={**AUTO, "prompt": "кот", "detail": True})
    assert r.status_code == 202
    done = wait_for(client, r.json()["id"], "succeeded")
    assert done["model"] == "flux2-klein-4b"  # photo → Klein, which has no detail pass


def test_auto_with_references_needs_a_capable_model(client: TestClient, services: Services) -> None:
    install_fake_model(services, "z-image-turbo", "nvfp4")
    img = wait_for(
        client,
        client.post("/api/v1/jobs", json={**AUTO, "prompt": "кот"}).json()["id"],
        "succeeded",
    )["image_ids"][0]
    r = client.post("/api/v1/jobs", json={**AUTO, "prompt": "такой же", "references": [img]})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "model_not_installed"
