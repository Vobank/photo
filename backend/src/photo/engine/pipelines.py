"""Graph builders, one per catalog ``pipeline`` value.

Each builder turns validated job params plus resolved model files into a graph whose
final node is a ``SaveImage`` with the given prefix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from photo.catalog import ModelFile, ModelSpec
from photo.engine.graph import Graph
from photo.schemas import GenerateParams


@dataclass(frozen=True, slots=True)
class BuiltGraph:
    graph: Graph
    output_node: str


type Builder = Callable[[GenerateParams, ModelSpec, dict[str, ModelFile], int, str], BuiltGraph]


def build_z_image(
    p: GenerateParams,
    spec: ModelSpec,
    files: dict[str, ModelFile],
    seed: int,
    prefix: str,
) -> BuiltGraph:
    d = spec.defaults
    g = Graph()
    unet = g.node("UNETLoader", unet_name=files["diffusion"].name, weight_dtype="default")
    clip = g.node(
        "CLIPLoader", clip_name=files["text_encoder"].name, type="lumina2", device="default"
    )
    vae = g.node("VAELoader", vae_name=files["vae"].name)
    model = g.node("ModelSamplingAuraFlow", model=unet[0], shift=d.shift or 3.0, sampling="flow")
    positive = g.node("CLIPTextEncode", text=p.prompt, clip=clip[0])
    if p.negative_prompt and (p.cfg or d.cfg) > 1:
        negative = g.node("CLIPTextEncode", text=p.negative_prompt, clip=clip[0])
    else:
        # Distilled turbo models run at cfg 1, where the negative branch is unused.
        negative = g.node("ConditioningZeroOut", conditioning=positive[0])
    latent = g.node("EmptySD3LatentImage", width=p.width, height=p.height, batch_size=p.batch_size)
    samples = g.node(
        "KSampler",
        seed=seed,
        steps=p.steps or d.steps,
        cfg=p.cfg if p.cfg is not None else d.cfg,
        sampler_name=d.sampler,
        scheduler=d.scheduler,
        denoise=1.0,
        model=model[0],
        positive=positive[0],
        negative=negative[0],
        latent_image=latent[0],
    )
    image = g.node("VAEDecode", samples=samples[0], vae=vae[0])
    out = g.node("SaveImage", images=image[0], filename_prefix=prefix)
    return BuiltGraph(g, out.id)


BUILDERS: dict[str, Builder] = {
    "z_image": build_z_image,
}


def build(
    p: GenerateParams, spec: ModelSpec, files: dict[str, ModelFile], seed: int, prefix: str
) -> BuiltGraph:
    try:
        builder = BUILDERS[spec.pipeline]
    except KeyError:
        raise ValueError(f"no graph builder for pipeline {spec.pipeline!r}") from None
    return builder(p, spec, files, seed, prefix)
