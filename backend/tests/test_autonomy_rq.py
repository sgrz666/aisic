from fastapi.testclient import TestClient

from edusci.app import create_app
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    make_dataset_candidate,
)


class FakeQueue:
    def __init__(self):
        self.jobs = []

    def enqueue(self, function, *args, **kwargs):
        self.jobs.append((function, args, kwargs))


def test_rq_autonomous_job_reaches_same_gate(monkeypatch, tmp_path):
    papers = [
        {
            "title": f"RQ evidence {index}",
            "doi": f"10.1/rq-{index}",
            "abstract": "Population and education resources are measurable in official data.",
            "year": 2025,
            "url": f"https://doi.org/10.1/rq-{index}",
        }
        for index in range(6)
    ]
    literature = [FakeLiteratureAdapter(papers)]
    datasets = [
        FakeDatasetAdapter(
            [make_dataset_candidate()], b"country,year,value\nCHN,2025,10\n"
        )
    ]
    monkeypatch.setattr(
        "edusci.tasks.jobs.default_literature_adapters", lambda: literature
    )
    monkeypatch.setattr(
        "edusci.tasks.jobs.default_dataset_adapters", lambda: datasets
    )
    queue = FakeQueue()
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'rq.db').as_posix()}"
    app = create_app(
        database_url=database_url,
        task_mode="rq",
        storage_root=tmp_path / "files",
        task_queue=queue,
        literature_adapters=literature,
        dataset_adapters=datasets,
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "RQ 自治研究", "idea_text": "人口变化对教育资源配置的影响"},
        ).json()["id"]
        queued = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs", json={}
        )
        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"
        assert len(queue.jobs) == 1

        function, args, kwargs = queue.jobs.pop()
        function(*args, **{key: value for key, value in kwargs.items() if key not in {"job_id", "job_timeout"}})

        run = client.get(
            f"/api/v1/autonomous-runs/{queued.json()['run_id']}"
        ).json()
        assert run["status"] == "awaiting_route_confirmation"
