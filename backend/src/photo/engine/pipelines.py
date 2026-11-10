"""Graph builders, one per catalog ``pipeline`` value.

Each builder turns validated job params plus resolved model files into a graph whose
final node is a ``SaveImage`` with the given prefix. Input pictures (references,
variation sources) arrive already uploaded to the engine, as engine file names.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from photo.auto import CLASSIFY_MAX_TOKENS, CLASSIFY_SYSTEM
from photo.catalog import ModelFile, ModelSpec
from photo.engine.graph import Graph, Link, NodeRef
from photo.schemas import MAX_PIXELS, GenerateParams
from photo.styles import ENHANCE_SYSTEM, Style, apply_style, enhance_request, get_style

# Longest prompt the language model may write (tokens).
ENHANCE_MAX_TOKENS = 320
# Second "detail" pass: how much larger, and how much it may change.
DETAIL_SCALE = 1.5
DETAIL_DENOISE = 0.38


@dataclass(frozen=True, slots=True)
class Capabilities:
    references: bool = False
    variation: bool = False
    detail: bool = False
    # Change an existing picture from an instruction (whole or inside a selection).
    edit: bool = False


@dataclass(frozen=True, slots=True)
class BuildInputs:
    """Engine file names of input pictures, in the order given in the params."""

    references: tuple[str, ...] = ()
    variation_source: str | None = None


@dataclass(frozen=True, slots=True)
class BuiltGraph:
    graph: Graph
    output_node: str
    # Preview node whose text is the prompt the model actually received (if enhanced).
    prompt_node: str | None = None
    final_size: tuple[int, int] = (0, 0)


type Builder = Callable[
    [GenerateParams, ModelSpec, dict[str, ModelFile], int, str, BuildInputs], BuiltGraph
]


@dataclass
class _Pipeline:
    build: Builder
    caps: Capabilities = field(default_factory=Capabilities)


# ---- shared pieces -------------------------------------------------------------------


def _prompt(
    g: Graph, clip: NodeRef, p: GenerateParams, seed: int, has_refs: bool
) -> tuple[str | Link, str | None]:
    """The positive prompt: plain text with the style suffix, or a language-model
    rewrite wired straight into the encoder. Returns (text, preview node id)."""
    return _prompt_with_style(g, clip, p, get_style(p.style), seed, has_refs)


def _prompt_with_style(
    g: Graph, clip: NodeRef, p: GenerateParams, style: Style | None, seed: int, has_refs: bool
) -> tuple[str | Link, str | None]:
    if not p.enhance:
        return apply_style(p.prompt, style), None
    generated = g.node(
        "TextGenerateV2",
        clip=clip[0],
        prompt=enhance_request(p.prompt, style, has_references=has_refs),
        system_prompt=ENHANCE_SYSTEM,
        max_length=ENHANCE_MAX_TOKENS,
        sampling_mode="on",
        **{
            "sampling_mode.temperature": 0.7,
            "sampling_mode.top_k": 40,
            "sampling_mode.top_p": 0.9,
            "sampling_mode.min_p": 0.05,
            "sampling_mode.repetition_penalty": 1.05,
            "sampling_mode.presence_penalty": 0.0,
            "sampling_mode.seed": seed,
        },
        thinking=False,
        use_default_template=True,
        mtp="auto",
    )
    preview = g.node("PreviewAny", source=generated[0])
    return generated[0], preview.id


def _snap16(v: float) -> int:
    return max(256, round(v / 16) * 16)


def detail_size(width: int, height: int) -> tuple[int, int]:
    """Second-pass size: 1.5x, capped by the pixel budget, multiples of 16."""
    scale = min(DETAIL_SCALE, math.sqrt(MAX_PIXELS / (width * height)))
    return _snap16(width * scale), _snap16(height * scale)


# ---- Z-Image -------------------------------------------------------------------------


def build_z_image(
    p: GenerateParams,
    spec: ModelSpec,
    files: dict[str, ModelFile],
    seed: int,
    prefix: str,
    inputs: BuildInputs,
) -> BuiltGraph:
    d = spec.defaults
    g = Graph()
    unet = g.node("UNETLoader", unet_name=files["diffusion"].name, weight_dtype="default")
    clip = g.node(
        "CLIPLoader", clip_name=files["text_encoder"].name, type="lumina2", device="default"
    )
    vae = g.node("VAELoader", vae_name=files["vae"].name)
    model = g.node("ModelSamplingAuraFlow", model=unet[0], shift=d.shift or 3.0, sampling="flow")

    text, prompt_node = _prompt(g, clip, p, seed, has_refs=False)
    positive = g.node("CLIPTextEncode", text=text, clip=clip[0])
    cfg = p.cfg if p.cfg is not None else d.cfg
    if p.negative_prompt and cfg > 1:
        negative = g.node("CLIPTextEncode", text=p.negative_prompt, clip=clip[0])
    else:
        # Distilled turbo models run at cfg 1, where the negative branch is unused.
        negative = g.node("ConditioningZeroOut", conditioning=positive[0])

    if inputs.variation_source:
        source = g.node("LoadImage", image=inputs.variation_source)
        fitted = g.node(
            "ImageScale",
            image=source[0],
            upscale_method="lanczos",
            width=p.width,
            height=p.height,
            crop="center",
        )
        encoded = g.node("VAEEncode", pixels=fitted[0], vae=vae[0])
        latent = g.node("RepeatLatentBatch", samples=encoded[0], amount=p.batch_size)
        denoise = p.variation_strength
    else:
        latent = g.node(
            "EmptySD3LatentImage", width=p.width, height=p.height, batch_size=p.batch_size
        )
        denoise = 1.0

    steps = p.steps or d.steps
    samples = g.node(
        "KSampler",
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler_name=d.sampler,
        scheduler=d.scheduler,
        denoise=denoise,
        model=model[0],
        positive=positive[0],
        negative=negative[0],
        latent_image=latent[0],
    )
    size = (p.width, p.height)
    if p.detail:
        size = detail_size(p.width, p.height)
        bigger = g.node(
            "LatentUpscale",
            samples=samples[0],
            upscale_method="bislerp",
            width=size[0],
            height=size[1],
            crop="disabled",
        )
        samples = g.node(
            "KSampler",
            seed=seed + 1,
            steps=steps,
            cfg=cfg,
            sampler_name=d.sampler,
            scheduler=d.scheduler,
            denoise=DETAIL_DENOISE,
            model=model[0],
            positive=positive[0],
            negative=negative[0],
            latent_image=bigger[0],
        )
    image = g.node("VAEDecode", samples=samples[0], vae=vae[0])
    out = g.node("SaveImage", images=image[0], filename_prefix=prefix)
    return BuiltGraph(g, out.id, prompt_node, size)


# ---- FLUX.2 Klein --------------------------------------------------------------------


def build_flux2_klein(
    p: GenerateParams,
    spec: ModelSpec,
    files: dict[str, ModelFile],
    seed: int,
    prefix: str,
    inputs: BuildInputs,
) -> BuiltGraph:
    d = spec.defaults
    g = Graph()
    unet = g.node("UNETLoader", unet_name=files["diffusion"].name, weight_dtype="default")
    clip = g.node(
        "CLIPLoader", clip_name=files["text_encoder"].name, type="flux2", device="default"
    )
    vae = g.node("VAELoader", vae_name=files["vae"].name)

    if p.enhance:
        # The same Qwen3-4B weights, loaded as a plain language model for writing.
        writer = g.node(
            "CLIPLoader",
            clip_name=files["text_encoder"].name,
            type="lumina2",
            device="default",
        )
        text, prompt_node = _prompt(g, writer, p, seed, has_refs=bool(inputs.references))
    else:
        text, prompt_node = _prompt(g, clip, p, seed, has_refs=bool(inputs.references))

    positive: NodeRef = g.node("CLIPTextEncode", text=text, clip=clip[0])
    negative: NodeRef = g.node("ConditioningZeroOut", conditioning=positive[0])
    # Each reference conditions both branches, as in the reference workflow.
    for name in inputs.references:
        loaded = g.node("LoadImage", image=name)
        scaled = g.node(
            "ImageScaleToTotalPixels",
            image=loaded[0],
            upscale_method="lanczos",
            megapixels=1.0,
            resolution_steps=16,
        )
        latent_ref = g.node("VAEEncode", pixels=scaled[0], vae=vae[0])
        positive = g.node("ReferenceLatent", conditioning=positive[0], latent=latent_ref[0])
        negative = g.node("ReferenceLatent", conditioning=negative[0], latent=latent_ref[0])

    latent = g.node(
        "EmptyFlux2LatentImage", width=p.width, height=p.height, batch_size=p.batch_size
    )
    steps = p.steps or d.steps
    sigmas = g.node("Flux2Scheduler", steps=steps, width=p.width, height=p.height)
    guider = g.node(
        "CFGGuider",
        model=unet[0],
        positive=positive[0],
        negative=negative[0],
        cfg=p.cfg if p.cfg is not None else d.cfg,
    )
    sampler = g.node("KSamplerSelect", sampler_name=d.sampler)
    noise = g.node("RandomNoise", noise_seed=seed)
    samples = g.node(
        "SamplerCustomAdvanced",
        noise=noise[0],
        guider=guider[0],
        sampler=sampler[0],
        sigmas=sigmas[0],
        latent_image=latent[0],
    )
    image = g.node("VAEDecode", samples=samples[0], vae=vae[0])
    out = g.node("SaveImage", images=image[0], filename_prefix=prefix)
    return BuiltGraph(g, out.id, prompt_node, (p.width, p.height))


def build_enhance(
    text_encoder: str, prompt: str, style: Style | None, seed: int, has_refs: bool
) -> BuiltGraph:
    """A graph that only rewrites a prompt (for the "Improve" button)."""
    g = Graph()
    clip = g.node("CLIPLoader", clip_name=text_encoder, type="lumina2", device="default")
    p = GenerateParams(model="enhance", prompt=prompt, enhance=True)
    _, preview = _prompt_with_style(g, clip, p, style, seed, has_refs)
    assert preview is not None
    return BuiltGraph(g, preview, preview)


def build_text(text_encoder: str, system: str, prompt: str, max_tokens: int) -> BuiltGraph:
    """A graph that only runs the language model once, greedily (same input, same output)."""
    g = Graph()
    clip = g.node("CLIPLoader", clip_name=text_encoder, type="lumina2", device="default")
    answer = g.node(
        "TextGenerateV2",
        clip=clip[0],
        prompt=prompt,
        system_prompt=system,
        max_length=max_tokens,
        sampling_mode="off",
        thinking=False,
        use_default_template=True,
        mtp="auto",
    )
    preview = g.node("PreviewAny", source=answer[0])
    return BuiltGraph(g, preview.id, preview.id)


def build_classify(text_encoder: str, prompt: str) -> BuiltGraph:
    """Label the request's medium and translate it (automatic mode).

    Greedy decoding: the same request always routes the same way, so seeds reproduce.
    """
    return build_text(text_encoder, CLASSIFY_SYSTEM, prompt, CLASSIFY_MAX_TOKENS)


PIPELINES: dict[str, _Pipeline] = {
    "z_image": _Pipeline(build_z_image, Capabilities(variation=True, detail=True)),
    "flux2_klein": _Pipeline(build_flux2_klein, Capabilities(references=True, edit=True)),
}


def capabilities(spec: ModelSpec) -> Capabilities:
    pipeline = PIPELINES.get(spec.pipeline)
    return pipeline.caps if pipeline else Capabilities()


def build(
    p: GenerateParams,
    spec: ModelSpec,
    files: dict[str, ModelFile],
    seed: int,
    prefix: str,
    inputs: BuildInputs | None = None,
) -> BuiltGraph:
    try:
        pipeline = PIPELINES[spec.pipeline]
    except KeyError:
        raise ValueError(f"no graph builder for pipeline {spec.pipeline!r}") from None
    return pipeline.build(p, spec, files, seed, prefix, inputs or BuildInputs())
