from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProblemStatementSection(BaseModel):
    current_limitation: str = Field(min_length=10)
    knowledge_gap: str = Field(min_length=10)
    research_question: str = Field(min_length=8)
    evidence_ids: list[str] = Field(default_factory=list)


class RationaleSection(BaseModel):
    innovation: str = Field(min_length=8)
    reasoning_chain: list[str] = Field(min_length=4, max_length=6)
    evidence_ids: list[str] = Field(default_factory=list)


class HypothesisV2(BaseModel):
    id: str
    null_hypothesis: str
    alternative_hypothesis: str
    direction: str
    falsification_criterion: str


class TechnicalDetail(BaseModel):
    purpose: str
    method: str
    stack: list[str] = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)
    execution_status: Literal["executed", "planned", "future_recommendation"]
    rationale: str


class DatasetDescriptor(BaseModel):
    name: str
    origin_type: Literal[
        "real_collected", "public_official", "synthetic_demo", "unknown"
    ]
    role: str
    rows: int | None = None
    columns: list[str] = Field(default_factory=list)
    provenance_url: str = ""
    license_name: str = ""
    content_hash: str = ""
    limitations: list[str] = Field(default_factory=list)


class TargetDataset(BaseModel):
    population: str
    features: list[str] = Field(min_length=1)
    label: str
    minimum_sample_size: int = Field(ge=1)
    collection_period: str
    format: str
    ethics: list[str] = Field(min_length=1)


class DatasetSection(BaseModel):
    source: list[DatasetDescriptor] = Field(default_factory=list)
    simulation_input: list[DatasetDescriptor] = Field(default_factory=list)
    target: TargetDataset


class MethodStep(BaseModel):
    step: int = Field(ge=1)
    name: str
    input: str
    procedure: str
    output: str


class BaselineSpec(BaseModel):
    name: str
    description: str
    purpose: str


class MetricSpec(BaseModel):
    name: str
    definition: str
    success_criterion: str


class ExperimentSection(BaseModel):
    baselines: list[BaselineSpec] = Field(min_length=1)
    metrics: list[MetricSpec] = Field(min_length=1)
    validation_design: str
    robustness_checks: list[str] = Field(default_factory=list)


class StatisticalFinding(BaseModel):
    method: str
    variables: list[str]
    estimate: float | None = None
    p_value: float | None = None
    confidence_interval_95: list[float | None] = Field(default_factory=list)
    effect_size: float | None = None
    interpretation: str


class ResultsSection(BaseModel):
    kind: Literal["observed_empirical", "simulation_feasibility", "expected_only"]
    status: str
    sample_size: int | None = None
    data_quality: dict = Field(default_factory=dict)
    statistical_findings: list[StatisticalFinding] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    feasibility_conclusion: str
    limitations: list[str] = Field(default_factory=list)


class LimitationsEthicsSection(BaseModel):
    causal_boundary: str
    sample_limitations: list[str] = Field(default_factory=list)
    privacy: list[str] = Field(default_factory=list)
    consent: list[str] = Field(default_factory=list)


class BibliographicReference(BaseModel):
    evidence_id: str
    authors: list[str] = Field(default_factory=list)
    title: str
    source: str = ""
    year: int | None = None
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    url: str
    reference_type: str = "EB/OL"
    formatted: str


class ResearchReportV2(BaseModel):
    schema_version: Literal[2] = 2
    paper_title: str = Field(min_length=15, max_length=80)
    abstract: str = Field(min_length=200, max_length=1200)
    keywords: list[str] = Field(min_length=3, max_length=5)
    problem_statement: ProblemStatementSection
    rationale: RationaleSection
    hypotheses: list[HypothesisV2] = Field(min_length=1)
    technical_details: list[TechnicalDetail] = Field(min_length=1)
    datasets: DatasetSection
    methods: list[MethodStep] = Field(min_length=1)
    experiments: ExperimentSection
    results: ResultsSection
    limitations_ethics: LimitationsEthicsSection
    references: list[BibliographicReference] = Field(default_factory=list)
    appendices: dict = Field(default_factory=dict)
