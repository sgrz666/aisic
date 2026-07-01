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
            f"/api/v1/projects/{project_id}/autonomous-runs", json={}
        )

        assert response.status_code == 202
        ref = response.json()
        run = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}").json()
        assert run["status"] == "awaiting_route_confirmation"
        events = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}/events")
        assert events.status_code == 200
        assert "event: progress" in events.text
        assert "awaiting_route_confirmation" in events.text
        candidates = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/dataset-candidates"
        ).json()
        assert candidates[0]["source"] == "world_bank"
        assert candidates[0]["selected"] is True


def test_cancel_and_route_resume_api(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        ref = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs", json={}
        ).json()

        canceled = client.post(f"/api/v1/autonomous-runs/{ref['run_id']}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

        second_project = create_project(client)
        second = client.post(
            f"/api/v1/projects/{second_project}/autonomous-runs", json={}
        ).json()
        client.post(
            f"/api/v1/projects/{second_project}/route-confirmations",
            json={"route": "A"},
        )
        resumed = client.post(f"/api/v1/autonomous-runs/{second['run_id']}/resume")
        assert resumed.status_code == 202
        assert resumed.json()["status"] == "completed"


def test_route_b_dataset_upload_automatically_resumes_run(tmp_path):
    with make_autonomy_client(tmp_path) as client:
        project_id = create_project(client)
        ref = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs", json={}
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
