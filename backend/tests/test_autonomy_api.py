from fastapi.testclient import TestClient

from edusci.app import create_app
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    FakeProvider,
    make_dataset_candidate,
    make_research_plan,
)


def make_autonomy_client(tmp_path):
    papers = [
        {
            "title": f"Education evidence {index}",
            "doi": f"10.1/api-{index}",
            "abstract": "Official population data supports education resource planning decisions.",
            "year": 2025,
            "url": f"https://doi.org/10.1/api-{index}",
        }
        for index in range(6)
    ]
    return TestClient(
        create_app(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'api.db').as_posix()}",
            task_mode="inline",
            storage_root=tmp_path / "files",
            model_provider=FakeProvider(make_research_plan().model_dump()),
            literature_adapters=[FakeLiteratureAdapter(papers)],
            dataset_adapters=[
                FakeDatasetAdapter(
                    [make_dataset_candidate()],
                    b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
                )
            ],
        )
    )


def create_project(client):
    return client.post(
        "/api/v1/projects",
        json={"title": "自治研究", "idea_text": "人口变化对教育资源配置的影响"},
    ).json()["id"]


def test_autonomous_run_api_reaches_gate_and_exposes_events(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)

        response = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        )

        assert response.status_code == 202
        ref = response.json()
        run = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}").json()
        assert run["status"] == "awaiting_route_confirmation"
        assert run["config"]["depth_mode"] == "adaptive_deep"
        assert run["current_iteration"] == 10
        assert run["source_count"] == 6
        assert run["fulltext_count"] == 0
        assert run["coverage"] == 0
        assert run["model_usage"] == {}
        events = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}/events")
        assert events.status_code == 200
        assert "event: progress" in events.text
        assert "awaiting_route_confirmation" in events.text
        candidates = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/dataset-candidates"
        ).json()
        assert candidates[0]["source"] == "world_bank"
        assert candidates[0]["selected"] is True

        research_state = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/research-state"
        )
        assert research_state.status_code == 200
        assert research_state.json()["limits"]["max_fulltexts"] == 60
        assert len(research_state.json()["iterations"]) == 10

        evidence_graph = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/evidence-graph"
        )
        assert evidence_graph.status_code == 200
        assert evidence_graph.json() == {"claims": [], "evidence": []}


def test_cancel_and_route_resume_api(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        ref = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        ).json()

        canceled = client.post(f"/api/v1/autonomous-runs/{ref['run_id']}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

        second_project = create_project(client)
        second = client.post(
            f"/api/v1/projects/{second_project}/autonomous-runs",
            json={"require_route_confirmation": True},
        ).json()
        client.post(
            f"/api/v1/projects/{second_project}/route-confirmations",
            json={"route": "A"},
        )
        resumed = client.post(f"/api/v1/autonomous-runs/{second['run_id']}/resume")
        assert resumed.status_code == 202
        assert resumed.json()["status"] == "completed"


def test_completed_project_can_start_a_new_autonomous_run(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        first = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        ).json()
        client.post(
            f"/api/v1/projects/{project_id}/route-confirmations",
            json={"route": "A"},
        )
        completed = client.post(
            f"/api/v1/autonomous-runs/{first['run_id']}/resume"
        )
        assert completed.json()["status"] == "completed"

        restarted = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        )

        assert restarted.status_code == 202
        second_run = client.get(
            f"/api/v1/autonomous-runs/{restarted.json()['run_id']}"
        ).json()
        assert second_run["status"] == "awaiting_route_confirmation"
        assert second_run["id"] != first["run_id"]
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["stage"] == "S2_GATE"
        assert project["route"] is None


def test_partially_progressed_project_can_start_a_new_autonomous_run(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        parsed = client.post(f"/api/v1/projects/{project_id}/idea-runs")
        assert parsed.status_code == 202
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S1_EVIDENCE"

        restarted = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        )

        assert restarted.status_code == 202
        run = client.get(
            f"/api/v1/autonomous-runs/{restarted.json()['run_id']}"
        ).json()
        assert run["status"] == "awaiting_route_confirmation"
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["stage"] == "S2_GATE"


def test_route_b_dataset_upload_automatically_resumes_run(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        ref = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"require_route_confirmation": True},
        ).json()
        client.post(
            f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "B"}
        )
        waiting = client.post(f"/api/v1/autonomous-runs/{ref['run_id']}/resume")
        assert waiting.json()["status"] == "awaiting_real_data"

        uploaded = client.post(
            f"/api/v1/projects/{project_id}/datasets",
            files={
                "file": (
                    "survey.csv",
                    b"group,outcome\nA,1\nA,2\nB,4\nB,5\n",
                    "text/csv",
                )
            },
        )

        assert uploaded.status_code == 201
        run = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}").json()
        assert run["status"] == "completed"
        project = client.get(f"/api/v1/projects/{project_id}").json()
        assert project["report"]["result_kind"] == "observed"
