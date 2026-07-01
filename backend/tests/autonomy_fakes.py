from __future__ import annotations

from edusci.autonomy.contracts import (
    DataRequirement,
    DatasetCandidateData,
    ResearchPlan,
    YearRange,
)


class FakeProvider:
    def __init__(self, response: dict):
        self.response = response
        self.calls = 0

    def complete_json(self, role: str, messages: list[dict]) -> dict:
        self.calls += 1
        return self.response


class FakeLiteratureAdapter:
    name = "fake_literature"

    def __init__(self, results: list[dict], fail: bool = False):
        self.results = results
        self.fail = fail
        self.calls = 0

    def search(self, query: str, limit: int) -> list[dict]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("literature source unavailable")
        return self.results[:limit]

    def related(self, source_id: str, limit: int) -> list[dict]:
        return []


class FakeDatasetAdapter:
    name = "fake_dataset"

    def __init__(
        self, candidates: list[DatasetCandidateData], payload: bytes, fail: bool = False
    ):
        self.candidates = candidates
        self.payload = payload
        self.fail = fail
        self.calls = 0

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("dataset source unavailable")
        return self.candidates[:limit]

    def download(
        self,
        candidate: DatasetCandidateData,
        geography: list[str],
        years: YearRange,
    ) -> bytes:
        return self.payload


def make_dataset_candidate(**overrides) -> DatasetCandidateData:
    values = {
        "source": "world_bank",
        "dataset_id": "SP.POP.TOTL",
        "title": "Population, total",
        "provenance_url": "https://api.worldbank.org/v2/indicator/SP.POP.TOTL",
        "download_url": "https://api.worldbank.org/v2/country/CHN/indicator/SP.POP.TOTL",
        "geographies": ["CHN"],
        "start_year": 2015,
        "end_year": 2026,
        "unit": "people",
        "frequency": "annual",
        "license_name": "CC BY 4.0",
        "license_url": "https://datacatalog.worldbank.org/public-licenses",
        "license_status": "allowed",
        "fields": ["country", "year", "value"],
        "variable_mapping": {"school-age population": "value"},
        "variable_coverage": 100,
        "estimated_size_bytes": 1024,
    }
    values.update(overrides)
    return DatasetCandidateData.model_validate(values)


def make_research_plan() -> ResearchPlan:
    return ResearchPlan.model_validate(
        {
            "problem_statement": "人口变化对基础教育资源配置的影响",
            "concepts": ["population", "education resources"],
            "variables": [
                {
                    "name": "school-age population",
                    "aliases_zh": ["学龄人口"],
                    "aliases_en": [],
                }
            ],
            "population": "基础教育阶段",
            "geographies": ["CHN"],
            "time_range": {"start": 2015, "end": 2026},
            "literature_queries": [
                {
                    "query": "school-age population education resources",
                    "language": "en",
                    "purpose": "broad",
                }
            ],
            "data_requirements": [
                {
                    "concept": "school-age population",
                    "unit_hint": "people",
                    "required": True,
                }
            ],
        }
    )
