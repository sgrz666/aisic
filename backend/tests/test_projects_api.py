from pathlib import Path

from fastapi.testclient import TestClient

from edusci.app import create_app


def make_client(tmp_path: Path) -> TestClient:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'test.db').as_posix()}"
    return TestClient(create_app(database_url=database_url, task_mode="inline"))


def test_project_research_flow_reaches_confirmed_route_b(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        created = client.post(
            "/api/v1/projects",
            json={"title": "AI 焦虑研究", "idea_text": "分析大学生 AI 焦虑度与专业的关系"},
        )
        assert created.status_code == 201
        project = created.json()
        project_id = project["id"]
        assert project["stage"] == "S0_IDEA"
        assert project["owner_id"] == "local-user"

        idea_task = client.post(f"/api/v1/projects/{project_id}/idea-runs")
        assert idea_task.status_code == 202
        assert idea_task.json()["status"] == "completed"

        evidence_task = client.post(
            f"/api/v1/projects/{project_id}/evidence-runs",
            json={
                "sources": [
                    {
                        "title": "大学生人工智能焦虑研究",
                        "source_type": "journal",
                        "url": "https://example.edu/paper/ai-anxiety",
                        "locator": "摘要",
                        "excerpt": "不同专业学生的人工智能焦虑可能存在差异。",
                        "verified": True,
                    }
                ]
            },
        )
        assert evidence_task.status_code == 202

        gate_task = client.post(f"/api/v1/projects/{project_id}/gate-runs")
        assert gate_task.status_code == 202

        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["stage"] == "S2_GATE"
        assert snapshot["suggested_route"] == "B"
        assert snapshot["scores"]["information_sufficiency"] < 70
        assert snapshot["scores"]["researchability"] >= 70
        assert snapshot["evidence_count"] == 1

        confirmed = client.post(
            f"/api/v1/projects/{project_id}/route-confirmations",
            json={"route": "B"},
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["route"] == "B"
        assert confirmed.json()["stage"] == "S3_DESIGN"


def test_evidence_card_contains_traceable_source_and_hash(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "资源配置", "idea_text": "人口变化对基础教育资源配置的影响"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(
            f"/api/v1/projects/{project_id}/evidence-runs",
            json={
                "sources": [
                    {
                        "title": "教育事业发展统计公报",
                        "source_type": "report",
                        "url": "https://example.gov/education-report",
                        "locator": "第 2 节",
                        "excerpt": "学龄人口规模变化影响学校布局。",
                        "verified": True,
                    }
                ]
            },
        )

        cards = client.get(f"/api/v1/projects/{project_id}/evidence").json()
        assert len(cards) == 1
        assert cards[0]["source_url"].startswith("https://")
        assert cards[0]["locator"] == "第 2 节"
        assert len(cards[0]["content_hash"]) == 64
        assert cards[0]["trust_status"] == "PASS"


def test_idea_parse_uses_injected_qwen_provider(tmp_path: Path) -> None:
    class FakeProvider:
        def complete_json(self, role: str, messages: list[dict]) -> dict:
            assert role == "generation"
            assert "大学生" in messages[-1]["content"]
            return {
                "problem_statement": "不同专业大学生的 AI 焦虑是否存在差异",
                "variables": ["专业", "AI焦虑"],
                "target_group": "大学生",
                "discipline": "教育学",
                "clarifying_questions": [],
            }

    database_url = f"sqlite+pysqlite:///{(tmp_path / 'qwen.db').as_posix()}"
    app = create_app(database_url=database_url, task_mode="inline", model_provider=FakeProvider())
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "AI 焦虑", "idea_text": "分析大学生 AI 焦虑度与专业的关系"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        snapshot = client.get(f"/api/v1/projects/{project_id}").json()

        assert snapshot["research_problem"]["problem_statement"] == "不同专业大学生的 AI 焦虑是否存在差异"
        assert snapshot["research_problem"]["variables"] == ["专业", "AI焦虑"]


def test_rq_mode_queues_then_worker_executes_the_same_task(tmp_path: Path) -> None:
    class FakeQueue:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def enqueue(self, function, *args, **kwargs):
            self.calls.append((function, args, kwargs))
            return object()

    queue = FakeQueue()
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'rq.db').as_posix()}"
    app = create_app(
        database_url=database_url,
        task_mode="rq",
        storage_root=tmp_path / "files",
        task_queue=queue,
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "异步任务", "idea_text": "大学生学习投入与反馈方式的关系"},
        ).json()["id"]
        queued = client.post(f"/api/v1/projects/{project_id}/idea-runs")

        assert queued.status_code == 202
        assert queued.json()["status"] == "queued"
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S0_IDEA"
        assert len(queue.calls) == 1

        function, args, _ = queue.calls[0]
        function(*args)

        assert client.get(f"/api/v1/tasks/{queued.json()['task_id']}").json()["status"] == "completed"
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S1_EVIDENCE"
