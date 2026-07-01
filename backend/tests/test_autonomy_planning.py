from pathlib import Path

from fastapi.testclient import TestClient

from edusci.app import create_app
from edusci.autonomy.planning import ResearchPlanner
from edusci.services.projects import require_project, run_idea_parse
from tests.autonomy_fakes import FakeProvider, make_research_plan


def test_planner_returns_bilingual_bounded_plan() -> None:
    response = make_research_plan().model_dump()
    response["literature_queries"].append(
        {
            "query": "学龄人口 基础教育资源配置",
            "language": "zh",
            "purpose": "broad",
        }
    )
    provider = FakeProvider(response)

    plan = ResearchPlanner(provider).plan("人口变化对基础教育资源配置的影响")

    assert {query.language for query in plan.literature_queries} == {"zh", "en"}
    assert len(plan.literature_queries) <= 8
    assert plan.data_requirements[0].required is True
    assert provider.calls == 1


def test_offline_planner_still_builds_queries_and_data_requirements() -> None:
    plan = ResearchPlanner().plan("人口变化对基础教育资源配置的影响")

    assert {query.language for query in plan.literature_queries} == {"zh", "en"}
    assert plan.variables
    assert plan.data_requirements


def test_idea_parse_can_reuse_research_plan_without_calling_model(tmp_path: Path) -> None:
    provider = FakeProvider({"unexpected": True})
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'plan.db').as_posix()}",
        task_mode="inline",
        model_provider=provider,
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "规划复用", "idea_text": "人口变化对基础教育资源配置的影响"},
        ).json()["id"]

        plan = ResearchPlanner().plan("人口变化对基础教育资源配置的影响")
        with app.state.session_factory() as session:
            project = require_project(session, project_id)
            run_idea_parse(
                session,
                project,
                model_provider=provider,
                research_plan=plan,
            )

        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["research_problem"]["problem_statement"] == plan.problem_statement
        assert provider.calls == 0
