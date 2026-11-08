import pytest

from photo.catalog import default_catalog
from photo.engine.graph import Graph, Link
from photo.engine.pipelines import build
from photo.schemas import GenerateParams


def _build(**overrides: object) -> dict:
    spec = default_catalog().get("z-image-turbo")
    params = GenerateParams(**{"model": "z-image-turbo", "prompt": "a red fox", **overrides})  # type: ignore[arg-type]
    built = build(params, spec, spec.variant_files(spec.variant("nvfp4")), 42, "photo/job")
    api = built.graph.to_api()
    assert api[built.output_node]["class_type"] == "SaveImage"
    return api


def _node(api: dict, class_type: str) -> dict:
    (node,) = [n for n in api.values() if n["class_type"] == class_type]
    return node["inputs"]


def test_z_image_graph_matches_reference_recipe() -> None:
    api = _build(width=1280, height=720, batch_size=2)
    assert _node(api, "UNETLoader")["unet_name"] == "z_image_turbo_nvfp4.safetensors"
    assert _node(api, "CLIPLoader")["type"] == "lumina2"
    assert _node(api, "ModelSamplingAuraFlow")["shift"] == 3.0
    ks = _node(api, "KSampler")
    assert (ks["seed"], ks["steps"], ks["cfg"], ks["sampler_name"]) == (42, 8, 1.0, "res_multistep")
    assert _node(api, "EmptySD3LatentImage") == {"width": 1280, "height": 720, "batch_size": 2}
    assert _node(api, "CLIPTextEncode")["text"] == "a red fox"
    assert "ConditioningZeroOut" in {n["class_type"] for n in api.values()}


def test_negative_prompt_used_only_with_cfg() -> None:
    api = _build(negative_prompt="blurry", cfg=4.0)
    texts = sorted(n["inputs"]["text"] for n in api.values() if n["class_type"] == "CLIPTextEncode")
    assert texts == ["a red fox", "blurry"]


def test_prompt_text_cannot_alter_graph_structure() -> None:
    evil = '"}, "99": {"class_type": "LoadImage"'
    api = _build(prompt=evil)
    assert _node(api, "CLIPTextEncode")["text"] == evil
    assert "LoadImage" not in {n["class_type"] for n in api.values()}


def test_graph_rejects_dangling_links() -> None:
    g = Graph()
    with pytest.raises(ValueError, match="unknown node"):
        g.node("VAEDecode", samples=Link("7", 0))


@pytest.mark.parametrize(
    "overrides",
    [
        {"width": 1000},
        {"width": 128},
        {"width": 2048, "height": 2064},
        {"seed": -1},
        {"prompt": ""},
    ],
)
def test_invalid_params_rejected(overrides: dict) -> None:
    with pytest.raises(ValueError):
        GenerateParams(model="z-image-turbo", **{"prompt": "x", **overrides})
