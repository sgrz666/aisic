from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
