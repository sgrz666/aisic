from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Sequence

from edusci.evaluation.contracts import (
    BenchmarkDocument,
    GoldEvidence,
    PredictedConclusion,
    PredictedEvidence,
    QualityCase,
    QualityGate,
    QualityMetrics,
    QualityPrediction,
    QualityReport,
    QualitySuite,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "research_quality_v1.json"


def _build_case(spec: dict) -> QualityCase:
    case_id = spec["id"]
    subquestion_id = f"{case_id}-sq1"
    support_id = f"{case_id}-support"
    second_stance = "counter" if spec["scenario"] == "conflict" else "qualifies"
    second_id = f"{case_id}-{second_stance}"
    documents = [
        BenchmarkDocument(
            id=support_id,
            title=f"{spec['topic']} evidence A",
            text=spec["primary_text"],
            relevance_grade=2,
            source_url=f"fixture://research-quality-v1/{support_id}",
            license_name="CC0-1.0",
            independent_group=f"{case_id}-group-a",
        ),
        BenchmarkDocument(
            id=second_id,
            title=f"{spec['topic']} evidence B",
            text=spec["secondary_text"],
            relevance_grade=1,
            source_url=f"fixture://research-quality-v1/{second_id}",
            license_name="CC0-1.0",
            independent_group=f"{case_id}-group-b",
        ),
        BenchmarkDocument(
            id=f"{case_id}-distractor",
            title=f"{spec['topic']} unrelated material",
            text=spec["distractor_text"],
            relevance_grade=0,
            source_url=f"fixture://research-quality-v1/{case_id}-distractor",
            license_name="CC0-1.0",
            independent_group=f"{case_id}-group-c",
        ),
    ]
    primary_stance = "qualifies" if spec["scenario"] == "insufficient" else "supports"
    evidence = [
        GoldEvidence(
            id=f"{case_id}-e1",
            document_id=support_id,
            excerpt=spec["primary_text"],
            claim=spec["claim"],
            stance=primary_stance,
            subquestion_id=subquestion_id,
        ),
        GoldEvidence(
            id=f"{case_id}-e2",
            document_id=second_id,
            excerpt=spec["secondary_text"],
            claim=spec["claim"],
            stance=second_stance,
            subquestion_id=subquestion_id,
        ),
    ]
    conclusion_allowed = spec["scenario"] != "insufficient"
    predicted_evidence = [
        PredictedEvidence(**item.model_dump(), locator="benchmark paragraph")
        for item in evidence
    ]
    conclusions = (
        [
            PredictedConclusion(
                statement=spec["claim"],
                evidence_ids=[item.id for item in evidence],
            )
        ]
        if conclusion_allowed
        else []
    )
    prediction = QualityPrediction(
        case_id=case_id,
        ranked_document_ids=[item.id for item in documents],
        evidence=predicted_evidence,
        conclusions=conclusions,
        restricted=not conclusion_allowed,
        counter_queries_executed=True,
    )
    return QualityCase(
        id=case_id,
        language=spec["language"],
        scenario=spec["scenario"],
        question=spec["question"],
        subquestions=[spec["question"]],
        documents=documents,
        gold_evidence=evidence,
        conclusion_allowed=conclusion_allowed,
        expected_stop_reason=(
            "insufficient_evidence" if not conclusion_allowed else "evidence_saturated"
        ),
        frozen_prediction=prediction.model_dump(mode="json"),
    )


def load_quality_suite(path: Path | None = None) -> QualitySuite:
    payload = json.loads((path or FIXTURE_PATH).read_text(encoding="utf-8"))
    return QualitySuite(
        id=payload["id"],
        gold_status=payload["gold_status"],
        cases=[_build_case(item) for item in payload["cases"]],
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _retrieval_metrics(case: QualityCase, prediction: QualityPrediction) -> tuple[float, float]:
    grades = {item.id: item.relevance_grade for item in case.documents}
    relevant = {document_id for document_id, grade in grades.items() if grade > 0}
    ranked = prediction.ranked_document_ids[:10]
    recall = len(relevant.intersection(ranked)) / len(relevant) if relevant else 1.0
    dcg = sum((2 ** grades.get(item, 0) - 1) / math.log2(index + 2) for index, item in enumerate(ranked))
    ideal = sorted(grades.values(), reverse=True)[:10]
    idcg = sum((2**grade - 1) / math.log2(index + 2) for index, grade in enumerate(ideal))
    return recall, dcg / idcg if idcg else 1.0


def _stance_macro_f1(suite: QualitySuite, predictions: dict[str, QualityPrediction]) -> float:
    gold_by_id = {
        item.id: item.stance for case in suite.cases for item in case.gold_evidence
    }
    predicted_by_id = {
        item.id: item.stance
        for prediction in predictions.values()
        for item in prediction.evidence
    }
    scores = []
    for stance in ("supports", "counter", "qualifies"):
        true_positive = sum(
            gold_by_id.get(item_id) == stance and predicted == stance
            for item_id, predicted in predicted_by_id.items()
        )
        false_positive = sum(
            gold_by_id.get(item_id) != stance and predicted == stance
            for item_id, predicted in predicted_by_id.items()
        )
        false_negative = sum(
            gold == stance and predicted_by_id.get(item_id) != stance
            for item_id, gold in gold_by_id.items()
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(2 * true_positive / denominator if denominator else 1.0)
    return _mean(scores)


def evaluate_predictions(
    suite: QualitySuite,
    predictions: list[QualityPrediction],
    *,
    model_mode: str = "offline",
) -> QualityReport:
    by_case = {item.case_id: item for item in predictions}
    recalls: list[float] = []
    ndcgs: list[float] = []
    grounding_checks: list[bool] = []
    unsupported = 0
    insufficient_restricted: list[bool] = []
    counter_searches: list[bool] = []

    for case in suite.cases:
        prediction = by_case[case.id]
        recall, ndcg = _retrieval_metrics(case, prediction)
        recalls.append(recall)
        ndcgs.append(ndcg)
        documents = {item.id: item for item in case.documents}
        evidence = {item.id: item for item in prediction.evidence}
        for item in evidence.values():
            document = documents.get(item.document_id)
            grounding_checks.append(
                bool(document and item.locator.strip() and item.excerpt in document.text)
            )
        for conclusion in prediction.conclusions:
            links = [evidence.get(item) for item in conclusion.evidence_ids]
            if (
                not case.conclusion_allowed
                or any(item is None for item in links)
                or not any(item and item.stance == "supports" for item in links)
            ):
                unsupported += 1
        if case.scenario == "insufficient":
            insufficient_restricted.append(prediction.restricted and not prediction.conclusions)
        counter_searches.append(prediction.counter_queries_executed)

    metrics = QualityMetrics(
        recall_at_10=round(_mean(recalls), 4),
        ndcg_at_10=round(_mean(ndcgs), 4),
        stance_macro_f1=round(_stance_macro_f1(suite, by_case), 4),
        grounding_rate=round(_mean([float(item) for item in grounding_checks]), 4),
        unsupported_conclusion_count=unsupported,
        restricted_report_recall=round(
            _mean([float(item) for item in insufficient_restricted]), 4
        ),
        counter_search_coverage=round(
            _mean([float(item) for item in counter_searches]), 4
        ),
    )
    failures = []
    if metrics.grounding_rate != 1.0:
        failures.append("grounding_rate_below_100_percent")
    if metrics.unsupported_conclusion_count:
        failures.append("unsupported_conclusions_present")
    if metrics.restricted_report_recall != 1.0:
        failures.append("insufficient_cases_not_restricted")
    if metrics.counter_search_coverage != 1.0:
        failures.append("counter_search_not_complete")
    stage = "full" if suite.gold_status == "approved" else "structural"
    if stage == "full":
        if metrics.recall_at_10 < 0.85:
            failures.append("recall_at_10_below_85_percent")
        if metrics.ndcg_at_10 < 0.80:
            failures.append("ndcg_at_10_below_80_percent")
        if metrics.stance_macro_f1 < 0.85:
            failures.append("stance_macro_f1_below_85_percent")
    return QualityReport(
        suite_id=suite.id,
        gold_status=suite.gold_status,
        model_mode=model_mode,
        case_count=len(suite.cases),
        metrics=metrics,
        gate=QualityGate(
            stage=stage,
            status="FAIL" if failures else "PASS",
            failures=failures,
        ),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the EduSci research-quality suite")
    parser.add_argument("--mode", choices=["offline"], default="offline")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    suite = load_quality_suite()
    predictions = [QualityPrediction.model_validate(case.frozen_prediction) for case in suite.cases]
    report = evaluate_predictions(suite, predictions, model_mode=args.mode)
    payload = report.model_dump(mode="json")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0 if report.gate.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
