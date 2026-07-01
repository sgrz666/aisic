from dataclasses import dataclass

import pytest

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import ProjectCreate
from edusci.autonomy.data_scout import DataScout
from edusci.autonomy.literature import LiteratureScout
from edusci.autonomy.orchestrator import AutonomousOrchestrator
from edusci.autonomy.planning import ResearchPlanner
from edusci.memory.database import build_session_factory
from edusci.services.analysis import save_dataset
from edusci.services.projects import confirm_route, create_project
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    FakeProvider,
    make_dataset_candidate,
    make_research_plan,
)


@dataclass
class RoutedContext:
    session: object
    project: object
    orchestrator: AutonomousOrchestrator
    store: LocalObjectStore
    run_id: str

    def confirm_and_resume(self, route: str):
        confirm_route(self.session, self.project, route)
        return self.orchestrator.resume(self.run_id)


def build_routed_context(root) -> RoutedContext:
    root.mkdir(parents=True, exist_ok=True)
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(root / 'route.db').as_posix()}"
    )
    session = factory()
    project = create_project(
        session,
        ProjectCreate(
            title="自动路径",
            idea_text="人口变化对教育资源配置的影响",
        ),
    )
    papers = [
        {
            "title": f"Education evidence {index}",
            "doi": f"10.1/e-{index}",
            "abstract": (
                "Population and education resources have a measurable relationship "
                "in official data."
            ),
            "year": 2024,
            "url": f"https://doi.org/10.1/e-{index}",
            "citation_count": 5,
        }
        for index in range(6)
    ]
    store = LocalObjectStore(root / "files")
    orchestrator = AutonomousOrchestrator(
        session=session,
        store=store,
        planner=ResearchPlanner(FakeProvider(make_research_plan().model_dump())),
        literature_scout=LiteratureScout([FakeLiteratureAdapter(papers)]),
        data_scout=DataScout(
            [
                FakeDatasetAdapter(
                    [make_dataset_candidate(fields=["group", "outcome"])],
                    b"group,outcome\nA,1\nA,2\nB,4\nB,5\n",
                )
            ],
            store,
        ),
    )
    run = orchestrator.start(project)
    return RoutedContext(session, project, orchestrator, store, run.id)


@pytest.mark.parametrize(
    ("route", "expected_status", "expected_stage", "result_kind"),
    [
        ("A", "completed", "COMPLETED", "observed"),
        ("B", "awaiting_real_data", "WAITING_FOR_DATA", None),
        ("C", "completed", "COMPLETED", "expected_only"),
        ("D", "completed", "BLOCKED", "expected_only"),
    ],
)
def test_resume_follows_confirmed_route(
    tmp_path, route, expected_status, expected_stage, result_kind
):
    routed = build_routed_context(tmp_path / route)

    run = routed.confirm_and_resume(route)

    assert run.status == expected_status
    assert routed.project.stage == expected_stage
    if result_kind:
        assert routed.project.report["result_kind"] == result_kind


def test_route_b_resumes_after_real_dataset_upload(tmp_path):
    routed = build_routed_context(tmp_path / "route-b-upload")
    run = routed.confirm_and_resume("B")
    assert run.status == "awaiting_real_data"

    dataset = save_dataset(
        routed.session,
        routed.store,
        routed.project,
        "survey.csv",
        "text/csv",
        b"group,outcome\nA,1\nA,2\nB,4\nB,5\n",
    )
    resumed = routed.orchestrator.resume_after_real_data(run.id, dataset.id)

    assert resumed.status == "completed"
    assert routed.project.stage == "COMPLETED"
    assert routed.project.report["result_kind"] == "observed"
