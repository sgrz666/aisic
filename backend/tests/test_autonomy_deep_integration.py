from fastapi.testclient import TestClient

from edusci.app import create_app
from edusci.autonomy.deep_research import FullTextArtifact
from tests.autonomy_fakes import (
    FakeDatasetAdapter,
    FakeLiteratureAdapter,
    make_dataset_candidate,
    make_research_plan,
)


class DeepProvider:
    usage = {"requests": 1, "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

    def complete_json(self, role, messages, schema=None):
        if role == "extractor":
            payload = {
                "claims": [
                    {
                        "statement": "Population change affects education resource allocation.",
                        "stance": "supports",
                        "confidence": 90,
                    }
                ]
            }
            return schema.model_validate(payload).model_dump(mode="json")
        return make_research_plan().model_dump(mode="json")


class FakeFullTextFetcher:
    def fetch(self, candidate):
        return FullTextArtifact(
            url=candidate["open_access_url"],
            mime_type="text/html",
            content=b"<h1>Results</h1><p>Population change affects education resource allocation.</p>",
            license_name="CC BY 4.0",
        )


def test_autonomous_run_executes_deep_research_and_exposes_graph(tmp_path) -> None:
    papers = [
        {
            "source_id": "open-1",
            "title": "Open evidence",
            "doi": "10.1/open-1",
            "abstract": "Population change affects education resource allocation decisions.",
            "year": 2025,
            "url": "https://doi.org/10.1/open-1",
            "open_access_url": "https://example.edu/open-1.html",
            "license_name": "CC BY 4.0",
        }
    ]
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'deep-api.db').as_posix()}",
        task_mode="inline",
        storage_root=tmp_path / "files",
        model_provider=DeepProvider(),
        literature_adapters=[FakeLiteratureAdapter(papers)],
        dataset_adapters=[
            FakeDatasetAdapter(
                [make_dataset_candidate()],
                b"country,year,value\nCHN,2024,100\nCHN,2025,101\n",
            )
        ],
        fulltext_fetcher=FakeFullTextFetcher(),
    )

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "Deep", "idea_text": "人口变化如何影响教育资源配置"},
        ).json()["id"]
        ref = client.post(
            f"/api/v1/projects/{project_id}/autonomous-runs",
            json={"initial_rounds": 1, "max_rounds": 1, "initial_fulltexts": 1, "max_fulltexts": 1},
        ).json()

        run = client.get(f"/api/v1/autonomous-runs/{ref['run_id']}").json()
        graph = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/evidence-graph"
        ).json()
        state = client.get(
            f"/api/v1/autonomous-runs/{ref['run_id']}/research-state"
        ).json()

    assert run["current_iteration"] == 1
    assert run["fulltext_count"] == 1
    assert run["claim_count"] == 1
    assert run["model_usage"]["total_tokens"] == 120
    assert run["quality_gate_status"] == "LIMITED"
    assert run["quality_metrics"]["subquestion_coverage"] == 33
    assert run["quality_metrics"]["independent_source_coverage"] == 0
    assert run["status"] == "awaiting_real_data"
    assert graph["claims"][0]["statement"].startswith("Population change")
    assert graph["claims"][0]["subquestion_ids"]
    assert graph["evidence"][0]["locator"] == "Results"
    assert graph["evidence"][0]["excerpt"].startswith("Population change")
    assert graph["evidence"][0]["validation_status"] == "validated"
    assert state["metrics"]["quality_gate_status"] == "LIMITED"
    assert state["metrics"]["counter_search_coverage"] == 100
