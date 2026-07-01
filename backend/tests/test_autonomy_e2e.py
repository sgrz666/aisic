from sqlalchemy import select

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import ProjectCreate
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.database import build_session_factory
from edusci.memory.models import AutonomousRunRecord, SearchAttemptRecord
from edusci.services.analysis import save_dataset
from edusci.services.autonomy import request_cancellation
from edusci.services.projects import confirm_route, create_project
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    FakeProvider,
    make_dataset_candidate,
    make_research_plan,
)
from tests.test_autonomous_routes import build_routed_context


def test_route_a_uses_real_official_data_for_observed_results(tmp_path):
    context = build_routed_context(tmp_path / "a")
    run = context.confirm_and_resume("A")
    assert run.status == "completed"
    assert context.project.report["result_kind"] == "observed"
    assert context.project.analysis_result["sample_size"] == 4


def test_route_b_waits_for_real_data_then_recovers(tmp_path):
    context = build_routed_context(tmp_path / "b")
    run = context.confirm_and_resume("B")
    assert run.status == "awaiting_real_data"
    assert context.project.analysis_result == {}
    dataset = save_dataset(
        context.session,
        context.store,
        context.project,
        "responses.csv",
        "text/csv",
        b"group,outcome\nA,1\nA,2\nB,4\nB,5\n",
    )
    recovered = context.orchestrator.resume_after_real_data(run.id, dataset.id)
    assert recovered.status == "completed"
    assert context.project.report["result_kind"] == "observed"


def test_route_c_never_fabricates_statistics(tmp_path):
    context = build_routed_context(tmp_path / "c")
    run = context.confirm_and_resume("C")
    assert run.status == "completed"
    assert context.project.analysis_result == {}
    assert context.project.report["result_kind"] == "expected_only"


def test_route_d_is_blocked_as_exploratory_only(tmp_path):
    context = build_routed_context(tmp_path / "d")
    run = context.confirm_and_resume("D")
    assert run.status == "completed"
    assert context.project.stage == "BLOCKED"
    assert context.project.review["overall"] == "BLOCK"


def test_literature_source_failure_degrades_to_healthy_adapter(tmp_path):
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'degrade.db').as_posix()}"
    )
    session = factory()
    project = create_project(
        session,
        ProjectCreate(title="降级", idea_text="人口变化对教育资源配置的影响"),
    )
    papers = [
        {
            "title": f"Healthy source {index}",
            "doi": f"10.1/healthy-{index}",
            "abstract": "Official population evidence supports education resource allocation.",
            "year": 2025,
            "url": f"https://doi.org/10.1/healthy-{index}",
        }
        for index in range(6)
    ]
    store = LocalObjectStore(tmp_path / "degrade-files")
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout(
            [FakeLiteratureAdapter([], fail=True), FakeLiteratureAdapter(papers)]
        ),
        data_scout=DataScout(
            [
                FakeDatasetAdapter(
                    [make_dataset_candidate()], b"country,year,value\nCHN,2025,1\n"
                )
            ],
            store,
        ),
    )
    run = orchestrator.start(project)
    attempts = session.scalars(
        select(SearchAttemptRecord).where(SearchAttemptRecord.run_id == run.id)
    ).all()
    assert run.status == "awaiting_route_confirmation"
    assert project.evidence_cards
    assert any(attempt.error for attempt in attempts)


def test_canceled_run_reuses_completed_discovery_checkpoints(tmp_path):
    context = build_routed_context(tmp_path / "recovery")
    literature_adapter = context.orchestrator.literature_scout.adapters[0]
    dataset_adapter = context.orchestrator.data_scout.adapters[0]
    calls_before = (literature_adapter.calls, dataset_adapter.calls)
    run = context.session.get(AutonomousRunRecord, context.run_id)
    assert run is not None
    request_cancellation(context.session, run)
    assert context.orchestrator.resume(run.id).status == "canceled"

    confirm_route(context.session, context.project, "A")
    run.cancel_requested = False
    context.session.add(run)
    context.session.commit()
    recovered = context.orchestrator.resume(run.id)

    assert recovered.status == "completed"
    assert (literature_adapter.calls, dataset_adapter.calls) == calls_before
