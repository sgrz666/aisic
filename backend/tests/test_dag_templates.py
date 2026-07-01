import pytest

from edusci.dag.templates import load_template


def test_three_stage_templates_have_declared_quality_gates() -> None:
    evidence = load_template("evidence")
    hypothesis = load_template("hypothesis")
    review = load_template("review")

    assert evidence.nodes[-1].name == "aggregate"
    assert hypothesis.nodes[-1].name == "polish"
    assert set(review.nodes[-2].dependencies) == {"citation", "statistics", "logic", "ethics"}
    assert all(node.quality_gate for template in (evidence, hypothesis, review) for node in template.nodes)


def test_unknown_dag_template_is_rejected() -> None:
    with pytest.raises(ValueError, match="未知 DAG 模板"):
        load_template("self_mutating")

