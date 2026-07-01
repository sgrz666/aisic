from edusci.analysis.storage import LocalObjectStore
from edusci.autonomy.data_scout import DataScout
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    make_dataset_candidate,
    make_research_plan,
)


def test_data_scout_selects_only_traceable_allowed_candidate(tmp_path):
    plan = make_research_plan()
    allowed_candidate = make_dataset_candidate()
    unlicensed_candidate = make_dataset_candidate(
        dataset_id="blocked",
        license_status="blocked",
        license_name="All rights reserved",
        score=100,
    )
    scout = DataScout(
        adapters=[
            FakeDatasetAdapter(
                [allowed_candidate, unlicensed_candidate],
                b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
            )
        ],
        store=LocalObjectStore(tmp_path),
    )

    result = scout.discover_and_select(plan, project_id="p1")

    assert result.status == "selected"
    assert result.selected is not None
    assert result.selected.dataset_id == allowed_candidate.dataset_id
    assert result.selected.score >= 70
    assert result.asset is not None
    assert result.asset.content_hash
    assert result.asset.row_count > 0
    assert result.provenance is not None
    assert result.provenance.transformations == ["source_json_to_tabular"]
    assert result.candidates[1].excluded_reason == "license_not_allowed"


def test_data_scout_returns_no_selection_when_variable_coverage_is_low(tmp_path):
    plan = make_research_plan()
    low_coverage = make_dataset_candidate(variable_coverage=40)
    adapter = FakeDatasetAdapter(
        [low_coverage], b"country,year,value\nCHN,2024,100\n"
    )

    result = DataScout([adapter], LocalObjectStore(tmp_path)).discover_and_select(
        plan, "p1"
    )

    assert result.status == "no_usable_dataset"
    assert result.selected is None
    assert result.asset is None
    assert result.candidates[0].excluded_reason == "variable_coverage_below_70"


def test_data_scout_pauses_when_downloaded_dataset_contains_pii(tmp_path):
    candidate = make_dataset_candidate(fields=["name", "year", "value"])
    adapter = FakeDatasetAdapter(
        [candidate], b"name,year,value\nAlice,2024,100\n"
    )

    result = DataScout([adapter], LocalObjectStore(tmp_path)).discover_and_select(
        make_research_plan(), "p1"
    )

    assert result.status == "paused_risk"
    assert result.selected is not None
    assert result.asset is None
    assert result.risk_report["pii_columns"] == ["name"]
