from pathlib import Path

from fastapi.testclient import TestClient

from edusci.app import create_app


def test_feedback_signal_is_recorded_without_mutating_workflow(tmp_path: Path) -> None:
    app = create_app(database_url=f"sqlite+pysqlite:///{(tmp_path / 'feedback.db').as_posix()}")
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"title": "反馈演化", "idea_text": "大学生反馈方式与学习投入的关系"},
        ).json()
        response = client.post(
            f"/api/v1/projects/{project['id']}/feedback-signals",
            json={
                "kind": "user_correction",
                "target": "idea_parser",
                "message": "应把反馈方式拆成及时性与具体性两个维度",
            },
        )

        assert response.status_code == 201
        assert response.json()["status"] == "recorded"
        assert response.json()["auto_applied"] is False
        unchanged = client.get(f"/api/v1/projects/{project['id']}").json()
        assert unchanged["stage"] == "S0_IDEA"

