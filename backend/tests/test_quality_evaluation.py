import json
from pathlib import Path

from edusci.evaluation.contracts import QualityPrediction
from edusci.evaluation.runner import evaluate_predictions, load_quality_suite, main


def test_quality_suite_contains_24_balanced_draft_cases() -> None:
    suite = load_quality_suite()

    assert suite.id == "research-quality-v1"
    assert suite.gold_status == "draft"
    assert len(suite.cases) == 24
    assert sum(case.language == "zh" for case in suite.cases) == 12
    assert sum(case.language == "en" for case in suite.cases) == 12
    assert {
        scenario: sum(case.scenario == scenario for case in suite.cases)
        for scenario in ("support", "conflict", "insufficient")
    } == {"support": 8, "conflict": 8, "insufficient": 8}
    assert all(case.documents and case.gold_evidence for case in suite.cases)


def test_quality_metrics_and_draft_gate_are_deterministic() -> None:
    suite = load_quality_suite()
    predictions = [QualityPrediction.model_validate(case.frozen_prediction) for case in suite.cases]

    report = evaluate_predictions(suite, predictions)

    assert report.case_count == 24
    assert report.metrics.recall_at_10 == 1.0
    assert report.metrics.ndcg_at_10 == 1.0
    assert report.metrics.stance_macro_f1 == 1.0
    assert report.metrics.grounding_rate == 1.0
    assert report.metrics.unsupported_conclusion_count == 0
    assert report.metrics.restricted_report_recall == 1.0
    assert report.metrics.counter_search_coverage == 1.0
    assert report.gate.stage == "structural"
    assert report.gate.status == "PASS"


def test_quality_cli_writes_machine_readable_report(tmp_path: Path) -> None:
    output = tmp_path / "quality.json"

    exit_code = main(["--mode", "offline", "--output", str(output)])

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["suite_id"] == "research-quality-v1"
    assert payload["gate"]["status"] == "PASS"
    assert payload["model_mode"] == "offline"
