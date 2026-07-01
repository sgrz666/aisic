from sqlalchemy import select

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import ProjectCreate
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.database import build_session_factory
from edusci.memory.models import (
    DatasetAssetRecord,
    DatasetCandidateRecord,
    NodeCheckpointRecord,
    ResearchPlanRecord,
)
from edusci.services.projects import create_project
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    FakeProvider,
    make_dataset_candidate,
    make_research_plan,
)


def test_orchestrator_runs_to_human_gate_and_reuses_checkpoints(tmp_path):
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'auto.db').as_posix()}"
    )
    session = factory()
    project = create_project(
        session,
        ProjectCreate(
            title="资源配置",
            idea_text="人口变化对基础教育资源配置的影响",
        ),
    )
    literature_adapter = FakeLiteratureAdapter(
        [
            {
                "title": f"Population and school resources {index}",
                "doi": f"10.1/resource-{index}",
                "abstract": (
                    "School-age population predicts demand for schools and teachers "
                    "in education systems."
                ),
                "year": 2024,
                "url": f"https://doi.org/10.1/resource-{index}",
                "citation_count": 10,
            }
            for index in range(6)
        ]
    )
    dataset_adapter = FakeDatasetAdapter(
        [make_dataset_candidate()],
        b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
    )
    store = LocalObjectStore(tmp_path / "files")
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout([literature_adapter]),
        data_scout=DataScout([dataset_adapter], store),
    )

    run = orchestrator.start(project)

    assert run.status == "awaiting_route_confirmation"
    assert project.stage == "S2_GATE"
    assert project.suggested_route == "A"
    assert literature_adapter.calls > 0
    assert dataset_adapter.calls > 0
    assert session.scalar(select(ResearchPlanRecord).where(ResearchPlanRecord.run_id == run.id))
    assert session.scalar(
        select(DatasetCandidateRecord).where(DatasetCandidateRecord.run_id == run.id)
    )
    assert session.scalar(
        select(DatasetAssetRecord).where(DatasetAssetRecord.run_id == run.id)
    )

    first_calls = (literature_adapter.calls, dataset_adapter.calls)
    resumed = orchestrator.resume(run.id)

    assert resumed.id == run.id
    assert (literature_adapter.calls, dataset_adapter.calls) == first_calls
    checkpoints = session.scalars(
        select(NodeCheckpointRecord).where(NodeCheckpointRecord.run_id == run.id)
    ).all()
    assert {checkpoint.node_name for checkpoint in checkpoints} >= {
        "planning",
        "idea_parse",
        "literature",
        "data_discovery",
        "evidence_persist",
        "gate",
    }


def test_orchestrator_recommends_route_b_without_a_usable_dataset(tmp_path):
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'no-data.db').as_posix()}"
    )
    session = factory()
    project = create_project(
        session,
        ProjectCreate(title="问卷研究", idea_text="大学生人工智能焦虑及其影响因素"),
    )
    papers = [
        {
            "title": f"AI anxiety in students {index}",
            "doi": f"10.1/anxiety-{index}",
            "abstract": "AI anxiety among university students can be measured using survey scales.",
            "year": 2025,
            "url": f"https://doi.org/10.1/anxiety-{index}",
        }
        for index in range(6)
    ]
    low_coverage = make_dataset_candidate(variable_coverage=30)
    store = LocalObjectStore(tmp_path / "files")
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout([FakeLiteratureAdapter(papers)]),
        data_scout=DataScout(
            [FakeDatasetAdapter([low_coverage], b"country,year,value\nCHN,2024,1\n")],
            store,
        ),
    )

    run = orchestrator.start(project)

    assert run.status == "awaiting_route_confirmation"
    assert project.suggested_route == "B"
