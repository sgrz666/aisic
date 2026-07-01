from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class AutonomousStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    SEARCHING_LITERATURE = "searching_literature"
    SEARCHING_DATASETS = "searching_datasets"
    RANKING_SOURCES = "ranking_sources"
    VALIDATING_EVIDENCE = "validating_evidence"
    AWAITING_ROUTE = "awaiting_route_confirmation"
    DESIGNING_STUDY = "designing_study"
    DOWNLOADING_DATASET = "downloading_dataset"
    ANALYZING = "analyzing"
    GENERATING_REPORT = "generating_report"
    REVIEWING = "reviewing"
    AWAITING_REAL_DATA = "awaiting_real_data"
    PAUSED_RISK = "paused_risk"
    FAILED = "failed"
    CANCELED = "canceled"
    COMPLETED = "completed"


class VariableSpec(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases_zh: list[str] = Field(default_factory=list)
    aliases_en: list[str] = Field(default_factory=list)


class YearRange(BaseModel):
    start: int = Field(ge=1900, le=2100)
    end: int = Field(ge=1900, le=2100)

    @model_validator(mode="after")
    def ordered(self) -> YearRange:
        if self.start > self.end:
            raise ValueError("开始年份不能晚于结束年份")
        return self


class LiteratureQuery(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    language: Literal["zh", "en"]
    purpose: Literal["broad", "gap", "citation"]


class DataRequirement(BaseModel):
    concept: str = Field(min_length=1, max_length=300)
    unit_hint: str = Field(default="", max_length=100)
    required: bool = True


class ResearchPlan(BaseModel):
    problem_statement: str = Field(min_length=2, max_length=2000)
    concepts: list[str] = Field(min_length=1, max_length=20)
    variables: list[VariableSpec] = Field(default_factory=list, max_length=20)
    population: str = Field(default="待确认", max_length=300)
    geographies: list[str] = Field(default_factory=list, max_length=50)
    time_range: YearRange
    literature_queries: list[LiteratureQuery] = Field(min_length=1, max_length=8)
    data_requirements: list[DataRequirement] = Field(default_factory=list, max_length=20)


class LiteratureCandidate(BaseModel):
    source: str
    source_id: str
    title: str
    abstract: str = ""
    doi: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str
    license_url: str = ""
    citation_count: int = 0
    evidence_type: Literal["theory", "measurement", "method", "counter", "general"] = (
        "general"
    )
    relevance_score: int = Field(default=0, ge=0, le=100)
    exclusion_reason: str = ""


class SearchAttemptData(BaseModel):
    source: str
    query: str
    round_number: int
    result_count: int
    duration_ms: int
    error: str = ""


class LiteratureDiscoveryResult(BaseModel):
    candidates: list[LiteratureCandidate]
    attempts: list[SearchAttemptData]
    rounds_completed: int
    stop_reason: str


class DatasetCandidateData(BaseModel):
    source: str
    dataset_id: str
    title: str
    description: str = ""
    provenance_url: str
    download_url: str
    geographies: list[str] = Field(default_factory=list)
    start_year: int | None = None
    end_year: int | None = None
    unit: str = ""
    frequency: str = ""
    license_name: str = ""
    license_url: str = ""
    license_status: Literal["allowed", "review", "blocked"] = "review"
    fields: list[str] = Field(default_factory=list)
    variable_mapping: dict[str, str] = Field(default_factory=dict)
    variable_coverage: int = Field(default=0, ge=0, le=100)
    score: int = Field(default=0, ge=0, le=100)
    estimated_size_bytes: int | None = None
    excluded_reason: str = ""


class DatasetAssetData(BaseModel):
    candidate_id: str
    storage_path: str
    content_hash: str
    row_count: int
    column_count: int
    data_schema: dict
    quality_report: dict


class ProvenanceData(BaseModel):
    source: str
    source_url: str
    retrieved_at: datetime
    content_hash: str
    license_name: str = ""
    license_url: str = ""
    transformations: list[str] = Field(default_factory=list)


class AutonomousEventData(BaseModel):
    run_id: str
    node: str
    message: str
    progress: int = Field(ge=0, le=100)
    timestamp: datetime


class CheckpointOutput(BaseModel):
    node_name: str
    input_hash: str
    output: dict
    reused: bool
