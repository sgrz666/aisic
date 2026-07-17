from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from edusci.autonomy.contracts import AutonomousStatus


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    idea_text: str = Field(min_length=4, max_length=5000)
    owner_id: str = "local-user"


class ProjectSnapshot(BaseModel):
    id: str
    owner_id: str
    title: str
    idea_text: str
    stage: str
    route: str | None
    suggested_route: str | None
    research_problem: dict
    scores: dict
    study_design: dict
    analysis_result: dict
    report: dict
    review: dict
    evidence_count: int


class SourceInput(BaseModel):
    title: str
    source_type: str = "web"
    url: str = ""
    locator: str = ""
    excerpt: str
    verified: bool = False
    bibliographic: dict = Field(default_factory=dict)


class EvidenceRunRequest(BaseModel):
    sources: list[SourceInput] = Field(default_factory=list)


class EvidenceCardView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    source_type: str
    source_url: str
    locator: str
    excerpt: str
    claim: str
    content_hash: str
    trust_status: str
    locked: bool


class RouteConfirmation(BaseModel):
    route: Literal["A", "B", "C", "D"]


class TaskRef(BaseModel):
    task_id: str
    status: str
    resource_id: str | None = None


class DatasetView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    file_name: str
    row_count: int
    column_count: int
    data_schema: dict
    quality_report: dict


class AnalysisRunRequest(BaseModel):
    dataset_id: str
    outcome_column: str | None = None
    group_column: str | None = None


class TaskView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    kind: str
    status: str
    resource_id: str | None
    retryable: bool
    error: dict


class DocumentView(BaseModel):
    id: str
    project_id: str
    file_name: str
    content_hash: str
    page_count: int
    parse_status: str
    chunk_count: int


class FeedbackSignalCreate(BaseModel):
    kind: str = Field(min_length=2, max_length=60)
    target: str = Field(min_length=2, max_length=120)
    message: str = Field(min_length=4, max_length=3000)


class FeedbackSignalView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    kind: str
    target: str
    message: str
    status: str
    auto_applied: bool
    proposal: dict


class AutonomousRunCreate(BaseModel):
    max_literature_rounds: int = Field(default=3, ge=1, le=3)
    max_results_per_query: int = Field(default=10, ge=1, le=50)
    depth_mode: Literal["adaptive_deep", "fixed"] = "adaptive_deep"
    initial_rounds: int = Field(default=5, ge=1, le=10)
    max_rounds: int = Field(default=10, ge=1, le=10)
    initial_fulltexts: int = Field(default=20, ge=1, le=60)
    max_fulltexts: int = Field(default=60, ge=1, le=60)
    soft_timeout_minutes: int = Field(default=60, ge=5, le=120)
    hard_timeout_minutes: int = Field(default=120, ge=5, le=120)
    require_route_confirmation: bool = False


class AutonomousRunRef(BaseModel):
    task_id: str | None = None
    run_id: str
    status: str


class AutonomousRunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    task_id: str | None
    status: AutonomousStatus
    current_node: str
    config: dict
    pause_reason: dict
    cancel_requested: bool
    error: dict
    current_iteration: int
    source_count: int
    fulltext_count: int
    claim_count: int
    coverage: int
    counter_evidence_coverage: int
    model_usage: dict
    stop_reason: str
    degraded_sources: list


class DatasetCandidateView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    project_id: str
    source: str
    external_id: str
    title: str
    provenance_url: str
    score: int
    selected: bool
    candidate_json: dict


class ReportRegenerationRequest(BaseModel):
    refresh_evidence: bool = True


class ReportArtifactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version: int
    schema_version: int
    report_json: dict
    review_json: dict
    generation_config: dict


class DatasetProvenanceUpdate(BaseModel):
    origin_type: Literal[
        "real_collected", "public_official", "synthetic_demo", "unknown"
    ]
    source_name: str = ""
    source_url: str = ""
    license_name: str = ""
    collection_period: str = ""
    confirmed: bool = False


class DatasetProvenanceView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    dataset_id: str
    project_id: str
    origin_type: str
    source_name: str
    source_url: str
    license_name: str
    collection_period: str
    confirmed: bool
