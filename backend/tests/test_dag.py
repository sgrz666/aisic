from edusci.dag.executor import DAGExecutor, DAGNode, InMemoryTraceStore


def test_dag_executes_dependencies_before_consumer() -> None:
    order: list[str] = []

    def search(_: dict, __: dict) -> dict:
        order.append("search")
        return {"sources": ["s1"]}

    def extract(_: dict, parents: dict) -> dict:
        order.append("extract")
        return {"cards": parents["search"]["sources"]}

    executor = DAGExecutor(InMemoryTraceStore())
    result = executor.run(
        [
            DAGNode("extract", ("search",), extract),
            DAGNode("search", (), search),
        ],
        context={"project_id": "p1"},
        run_key="evidence:p1:v1",
    )

    assert order == ["search", "extract"]
    assert result.outputs["extract"] == {"cards": ["s1"]}


def test_dag_reuses_completed_run_key() -> None:
    calls = 0

    def operator(_: dict, __: dict) -> dict:
        nonlocal calls
        calls += 1
        return {"ok": True}

    store = InMemoryTraceStore()
    executor = DAGExecutor(store)
    nodes = [DAGNode("only", (), operator)]

    first = executor.run(nodes, {}, "stable-input-hash")
    second = executor.run(nodes, {}, "stable-input-hash")

    assert calls == 1
    assert second is first

