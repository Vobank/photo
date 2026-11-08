"""Tiny builder for ComfyUI API-format graphs.

g = Graph()
model = g.node("UNETLoader", unet_name="x.safetensors", weight_dtype="default")
g.node("ModelSamplingAuraFlow", model=model[0], shift=3.0)
g.to_api()  # → {"1": {"class_type": "UNETLoader", "inputs": {...}}, ...}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

type Input = str | int | float | bool | Link | None


@dataclass(frozen=True, slots=True)
class Link:
    node_id: str
    output: int

    def to_api(self) -> list[str | int]:
        return [self.node_id, self.output]


@dataclass(frozen=True, slots=True)
class NodeRef:
    id: str

    def __getitem__(self, output: int) -> Link:
        return Link(self.id, output)


@dataclass
class Graph:
    _nodes: dict[str, tuple[str, dict[str, Input]]] = field(default_factory=dict)

    def node(self, class_type: str, **inputs: Input) -> NodeRef:
        node_id = str(len(self._nodes) + 1)
        for name, value in inputs.items():
            if isinstance(value, Link) and value.node_id not in self._nodes:
                raise ValueError(f"{class_type}.{name} links to unknown node {value.node_id}")
        self._nodes[node_id] = (class_type, dict(inputs))
        return NodeRef(node_id)

    def class_types(self) -> list[str]:
        return [ct for ct, _ in self._nodes.values()]

    def to_api(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for node_id, (class_type, inputs) in self._nodes.items():
            out[node_id] = {
                "class_type": class_type,
                "inputs": {
                    k: (v.to_api() if isinstance(v, Link) else v)
                    for k, v in inputs.items()
                    if v is not None
                },
            }
        return out
