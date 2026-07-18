from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class BenchmarkDocument(BaseModel):
    id: str
    title: str
    text: str
    relevance_grade: int = Field(ge=0, le=2)
    source_url: str
    license_name: str
    independent_group: str


class GoldEvidence(BaseModel):
    id: str
    document_id: str
    excerpt: str
    claim: str
    stance: Literal["supports", "counter", "qualifies"]
    subquestion_id: str


class PredictedEvidence(GoldEvidence):
    locator: str = Field(min_length=1)


class PredictedConclusion(BaseModel):
    statement: str
    evidence_ids: list[str] = Field(min_length=1)


class QualityPrediction(BaseModel):
    case_id: str
    ranked_document_ids: list[str]
    evidence: list[PredictedEvidence]
    conclusions: list[PredictedConclusion] = Field(default_factory=list)
    restricted: bool
    counter_queries_executed: bool


class QualityCase(BaseModel):
    id: str
    language: Literal["zh", "en"]
    scenario: Literal["support", "conflict", "insufficient"]
    question: str
    subquestions: list[str] = Field(min_length=1)
    documents: list[BenchmarkDocument] = Field(min_length=1)
    gold_evidence: list[GoldEvidence] = Field(min_length=1)
    conclusion_allowed: bool
    expected_stop_reason: str
    frozen_prediction: dict


class QualitySuite(BaseModel):
    id: str
    gold_status: Literal["draft", "approved"]
    cases: list[QualityCase]


class QualityMetrics(BaseModel):
    recall_at_10: float
    ndcg_at_10: float
    stance_macro_f1: float
    grounding_rate: float
    unsupported_conclusion_count: int
    restricted_report_recall: float
    counter_search_coverage: float


class QualityGate(BaseModel):
    stage: Literal["structural", "full"]
    status: Literal["PASS", "FAIL"]
    failures: list[str] = Field(default_factory=list)


class QualityReport(BaseModel):
    suite_id: str
    gold_status: str
    model_mode: str
    case_count: int
    metrics: QualityMetrics
    gate: QualityGate
    model_metadata: dict = Field(default_factory=dict)
