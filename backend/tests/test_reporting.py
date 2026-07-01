from pathlib import Path

from fastapi.testclient import TestClient

from edusci.app import create_app
from edusci.memory.models import TaskRecord


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            database_url=f"sqlite+pysqlite:///{(tmp_path / 'report.db').as_posix()}",
            task_mode="inline",
            storage_root=tmp_path / "files",
        )
    )


def test_route_d_report_states_that_no_real_data_was_collected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "探索性问题", "idea_text": "人吃饭速度与眨眼频率的关系"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(f"/api/v1/projects/{project_id}/evidence-runs", json={"sources": []})
        client.post(f"/api/v1/projects/{project_id}/gate-runs")
        client.post(
            f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "D"}
        )
        client.post(f"/api/v1/projects/{project_id}/study-design-runs")

        report_task = client.post(f"/api/v1/projects/{project_id}/report-runs")
        assert report_task.status_code == 202
        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["stage"] == "S6_REVIEW"
        assert "未采集真实数据" in snapshot["report"]["results"]
        assert snapshot["report"]["result_kind"] == "expected_only"

        review_task = client.post(f"/api/v1/projects/{project_id}/review-runs")
        assert review_task.status_code == 202
        blocked = client.get(f"/api/v1/projects/{project_id}").json()
        assert blocked["stage"] == "BLOCKED"
        assert blocked["review"]["overall"] == "BLOCK"

        final_export = client.get(f"/api/v1/projects/{project_id}/report.docx?mode=final")
        assert final_export.status_code == 409
        draft_export = client.get(f"/api/v1/projects/{project_id}/report.docx?mode=draft")
        assert draft_export.status_code == 200
        assert draft_export.content[:2] == b"PK"


def test_task_events_are_exposed_as_finite_sse_stream(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "任务追踪", "idea_text": "大学生学习投入与反馈方式的关系"},
        ).json()["id"]
        task = client.post(f"/api/v1/projects/{project_id}/idea-runs").json()

        task_view = client.get(f"/api/v1/tasks/{task['task_id']}")
        assert task_view.status_code == 200
        assert task_view.json()["status"] == "completed"

        events = client.get(f"/api/v1/tasks/{task['task_id']}/events")
        assert events.status_code == 200
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "event: started" in events.text
        assert "event: completed" in events.text


def test_task_cancel_and_failed_node_retry_contract(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'tasks.db').as_posix()}",
        task_mode="inline",
        storage_root=tmp_path / "files",
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "任务恢复", "idea_text": "大学生反馈方式与学习投入的关系"},
        ).json()["id"]
        with app.state.session_factory() as session:
            queued = TaskRecord(project_id=project_id, kind="idea_parse", status="queued")
            failed = TaskRecord(
                project_id=project_id,
                kind="idea_parse",
                status="failed",
                retryable=True,
                error={"code": "TEMPORARY", "message": "临时错误"},
            )
            session.add_all([queued, failed])
            session.commit()
            queued_id, failed_id = queued.id, failed.id

        canceled = client.post(f"/api/v1/tasks/{queued_id}/cancel")
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"

        retried = client.post(f"/api/v1/tasks/{failed_id}/retry")
        assert retried.status_code == 202
        assert retried.json()["status"] == "completed"
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S1_EVIDENCE"


def test_s6_uses_review_role_without_overriding_deterministic_guard(tmp_path: Path) -> None:
    class FakeDualRoleProvider:
        def __init__(self) -> None:
            self.roles: list[str] = []

        def complete_json(self, role: str, messages: list[dict]) -> dict:
            self.roles.append(role)
            if role == "generation":
                return {
                    "problem_statement": "人吃饭速度与眨眼频率的关系",
                    "variables": ["吃饭速度", "眨眼频率"],
                    "target_group": "待确认",
                    "discipline": "教育学",
                    "clarifying_questions": [],
                }
            return {"verdict": "PASS", "notes": ["模型建议通过，但必须服从确定性规则"]}

    provider = FakeDualRoleProvider()
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'dual-role.db').as_posix()}",
        task_mode="inline",
        storage_root=tmp_path / "files",
        model_provider=provider,
    )
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "双角色复审", "idea_text": "人吃饭速度与眨眼频率的关系"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(f"/api/v1/projects/{project_id}/evidence-runs", json={"sources": []})
        client.post(f"/api/v1/projects/{project_id}/gate-runs")
        client.post(f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "D"})
        client.post(f"/api/v1/projects/{project_id}/study-design-runs")
        client.post(f"/api/v1/projects/{project_id}/report-runs")
        client.post(f"/api/v1/projects/{project_id}/review-runs")

        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert provider.roles == ["generation", "review"]
        assert snapshot["review"]["agent_review"]["verdict"] == "PASS"
        assert snapshot["review"]["overall"] == "BLOCK"


def test_unverified_source_is_excluded_from_report_references(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "引用门禁", "idea_text": "大学生学习投入与反馈方式的关系"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(
            f"/api/v1/projects/{project_id}/evidence-runs",
            json={
                "sources": [
                    {
                        "title": "用户粘贴但尚未核验的材料",
                        "source_type": "web",
                        "url": "https://example.invalid/not-verifiable",
                        "locator": "第 1 节",
                        "excerpt": "这是一条尚未通过检索适配器核验的教育研究陈述。",
                    }
                ]
            },
        )
        client.post(f"/api/v1/projects/{project_id}/gate-runs")
        client.post(f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "C"})
        client.post(f"/api/v1/projects/{project_id}/study-design-runs")
        client.post(f"/api/v1/projects/{project_id}/report-runs")

        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["report"]["references"] == []
        assert snapshot["report"]["excluded_evidence_count"] == 1
