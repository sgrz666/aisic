from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

Operator = Callable[[dict, dict[str, dict]], dict]


@dataclass(frozen=True, slots=True)
class DAGNode:
    name: str
    dependencies: tuple[str, ...]
    operator: Operator


@dataclass(slots=True)
class DAGResult:
    run_key: str
    outputs: dict[str, dict]


class InMemoryTraceStore:
    def __init__(self) -> None:
        self._runs: dict[str, DAGResult] = {}

    def get(self, run_key: str) -> DAGResult | None:
        return self._runs.get(run_key)

    def put(self, result: DAGResult) -> DAGResult:
        self._runs[result.run_key] = result
        return result


class DAGExecutor:
    def __init__(self, trace_store: InMemoryTraceStore) -> None:
        self.trace_store = trace_store

    def run(self, nodes: list[DAGNode], context: dict, run_key: str) -> DAGResult:
        cached = self.trace_store.get(run_key)
        if cached is not None:
            return cached

        by_name = {node.name: node for node in nodes}
        if len(by_name) != len(nodes):
            raise ValueError("DAG 节点名称必须唯一")

        outputs: dict[str, dict] = {}
        pending = set(by_name)
        while pending:
            runnable = sorted(
                name
                for name in pending
                if all(dependency in outputs for dependency in by_name[name].dependencies)
            )
            if not runnable:
                missing = {
                    dep
                    for name in pending
                    for dep in by_name[name].dependencies
                    if dep not in by_name
                }
                if missing:
                    raise ValueError(f"DAG 依赖不存在: {sorted(missing)}")
                raise ValueError("DAG 存在循环依赖")

            for name in runnable:
                node = by_name[name]
                parents = {dep: outputs[dep] for dep in node.dependencies}
                outputs[name] = node.operator(context, parents)
                pending.remove(name)

        return self.trace_store.put(DAGResult(run_key=run_key, outputs=outputs))

