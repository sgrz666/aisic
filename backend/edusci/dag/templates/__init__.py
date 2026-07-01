from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import yaml


@dataclass(frozen=True, slots=True)
class TemplateNode:
    name: str
    operator: str
    dependencies: tuple[str, ...]
    model_role: str
    tools: tuple[str, ...]
    retry_limit: int
    quality_gate: str


@dataclass(frozen=True, slots=True)
class DAGTemplate:
    name: str
    artifact: str
    nodes: tuple[TemplateNode, ...]


ALLOWED = {"evidence", "hypothesis", "review"}


def load_template(name: str) -> DAGTemplate:
    if name not in ALLOWED:
        raise ValueError(f"未知 DAG 模板: {name}")
    path = files(__package__).joinpath(f"{name}.yaml")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    nodes = tuple(
        TemplateNode(
            name=item["name"],
            operator=item["operator"],
            dependencies=tuple(item.get("dependencies", [])),
            model_role=item.get("model_role", "generation"),
            tools=tuple(item.get("tools", [])),
            retry_limit=int(item.get("retry_limit", 2)),
            quality_gate=item["quality_gate"],
        )
        for item in raw["nodes"]
    )
    return DAGTemplate(name=raw["name"], artifact=raw["artifact"], nodes=nodes)

