from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from edusci.analysis.engine import profile_dataframe
from edusci.analysis.storage import LocalObjectStore
from edusci.autonomy.contracts import (
    DatasetAssetData,
    DatasetCandidateData,
    ProvenanceData,
    ResearchPlan,
)
from edusci.integrations.datasets.base import DatasetSourceAdapter

MAX_DATASET_BYTES = 50 * 1024 * 1024
OFFICIAL_SOURCES = {"world_bank", "unicef", "unesco_uis", "china_moe"}


class DataScoutResult(BaseModel):
    status: str
    candidates: list[DatasetCandidateData] = Field(default_factory=list)
    selected: DatasetCandidateData | None = None
    asset: DatasetAssetData | None = None
    provenance: ProvenanceData | None = None
    risk_report: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class DataScout:
    def __init__(
        self, adapters: list[DatasetSourceAdapter], store: LocalObjectStore
    ) -> None:
        self.adapters = adapters
        self.store = store

    def discover_and_select(
        self, plan: ResearchPlan, project_id: str
    ) -> DataScoutResult:
        candidates: list[DatasetCandidateData] = []
        candidate_adapters: dict[tuple[str, str], DatasetSourceAdapter] = {}
        errors: list[str] = []
        seen: set[tuple[str, str]] = set()

        for requirement in plan.data_requirements:
            for adapter in self.adapters:
                try:
                    found = adapter.search(requirement, limit=10)
                except RuntimeError as exc:
                    errors.append(f"{adapter.name}: {exc}")
                    continue
                for raw_candidate in found:
                    key = (raw_candidate.source, raw_candidate.dataset_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    scored = self._score(raw_candidate, plan, requirement.unit_hint)
                    candidates.append(scored)
                    candidate_adapters[key] = adapter

        eligible = [item for item in candidates if not item.excluded_reason]
        if not eligible:
            return DataScoutResult(
                status="no_usable_dataset", candidates=candidates, errors=errors
            )

        selected = max(eligible, key=lambda item: item.score)
        adapter = candidate_adapters[(selected.source, selected.dataset_id)]
        try:
            payload = adapter.download(selected, plan.geographies, plan.time_range)
            file_name = f"{selected.dataset_id}.csv"
            path, content_hash = self.store.save_remote_dataset(
                project_id, file_name, payload
            )
            frame = self.store.read_dataframe(path)
        except (RuntimeError, ValueError, OSError) as exc:
            return DataScoutResult(
                status="no_usable_dataset",
                candidates=candidates,
                selected=selected,
                errors=[*errors, f"{adapter.name}: {exc}"],
            )

        quality_report = profile_dataframe(frame)
        if quality_report["pii_columns"]:
            path.unlink(missing_ok=True)
            return DataScoutResult(
                status="paused_risk",
                candidates=candidates,
                selected=selected,
                risk_report=quality_report,
                errors=errors,
            )

        transformations = [self._transformation_for(selected.source)]
        provenance = ProvenanceData(
            source=selected.source,
            source_url=selected.provenance_url,
            retrieved_at=datetime.now(UTC),
            content_hash=content_hash,
            license_name=selected.license_name,
            license_url=selected.license_url,
            transformations=transformations,
        )
        asset = DatasetAssetData(
            candidate_id=selected.dataset_id,
            storage_path=str(path),
            content_hash=content_hash,
            row_count=len(frame),
            column_count=len(frame.columns),
            data_schema={str(column): str(dtype) for column, dtype in frame.dtypes.items()},
            quality_report=quality_report,
        )
        return DataScoutResult(
            status="selected",
            candidates=candidates,
            selected=selected,
            asset=asset,
            provenance=provenance,
            errors=errors,
        )

    @staticmethod
    def _score(
        candidate: DatasetCandidateData, plan: ResearchPlan, unit_hint: str
    ) -> DatasetCandidateData:
        exclusion = DataScout._exclusion_reason(candidate)
        if exclusion:
            return candidate.model_copy(update={"score": 0, "excluded_reason": exclusion})

        variable_points = candidate.variable_coverage * 0.35
        if not plan.geographies or set(plan.geographies) & set(candidate.geographies):
            geography_points = 12.5
        else:
            geography_points = 0.0

        requested_years = plan.time_range.end - plan.time_range.start + 1
        if candidate.start_year is None or candidate.end_year is None:
            time_points = 0.0
        else:
            overlap = max(
                0,
                min(candidate.end_year, plan.time_range.end)
                - max(candidate.start_year, plan.time_range.start)
                + 1,
            )
            time_points = 12.5 * min(1.0, overlap / requested_years)

        official_points = 15.0 if candidate.source in OFFICIAL_SOURCES else 0.0
        field_points = 7.5 if candidate.fields else 0.0
        unit_points = (
            7.5
            if not unit_hint
            or unit_hint.lower() in candidate.unit.lower()
            or candidate.unit.lower() in unit_hint.lower()
            else 0.0
        )
        completeness_points = 10.0 if candidate.estimated_size_bytes is not None else 5.0
        score = round(
            variable_points
            + geography_points
            + time_points
            + official_points
            + field_points
            + unit_points
            + completeness_points
        )
        return candidate.model_copy(update={"score": min(score, 100)})

    @staticmethod
    def _exclusion_reason(candidate: DatasetCandidateData) -> str:
        if candidate.license_status != "allowed":
            return "license_not_allowed"
        if candidate.variable_coverage < 70:
            return "variable_coverage_below_70"
        if candidate.estimated_size_bytes is not None and (
            candidate.estimated_size_bytes > MAX_DATASET_BYTES
        ):
            return "dataset_too_large"
        for url in (candidate.provenance_url, candidate.download_url):
            if urlparse(url).scheme != "https":
                return "non_https_source"
        return ""

    @staticmethod
    def _transformation_for(source: str) -> str:
        if source == "china_moe":
            return "source_html_to_tabular"
        return "source_json_to_tabular"
