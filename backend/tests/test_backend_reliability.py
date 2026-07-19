from pathlib import Path

from fastapi.testclient import TestClient
import pytest
import yaml
from sqlalchemy import event, text

from edusci.app import create_app
from edusci.api import routes
from edusci.memory.database import managed_session
from tests.autonomy_fakes import FakeDatasetAdapter, FakeLiteratureAdapter


class RecordingQueue:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def enqueue(self, function, *args, **kwargs):
        self.calls.append((function, args, kwargs))
        return object()


class FailingProvider:
    def complete_json(self, role: str, messages: list[dict], schema=None) -> dict:
        del role, messages, schema
        raise RuntimeError("model service unavailable")


def make_project(client: TestClient) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"title": "Reliable research", "idea_text": "AI use in higher education"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_cors_allows_the_configured_web_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WEB_PORT", "5174")
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'cors.db').as_posix()}"
    )

    with TestClient(app) as client:
        response = client.options(
            "/health",
            headers={
                "Origin": "http://127.0.0.1:5174",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_repeated_start_returns_the_active_run_without_duplicate_queue_job(
    tmp_path: Path,
) -> None:
    queue = RecordingQueue()
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'idempotent.db').as_posix()}",
        task_mode="rq",
        storage_root=tmp_path / "files",
        task_queue=queue,
        literature_adapters=[FakeLiteratureAdapter([])],
        dataset_adapters=[FakeDatasetAdapter([], b"")],
    )

    with TestClient(app) as client:
        project_id = make_project(client)
        first = client.post(f"/api/v1/projects/{project_id}/autonomous-runs", json={})
        second = client.post(f"/api/v1/projects/{project_id}/autonomous-runs", json={})
        latest = client.get(f"/api/v1/projects/{project_id}/autonomous-runs/latest")

    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["run_id"] == first.json()["run_id"]
    assert second.json()["status"] == "queued"
    assert len(queue.calls) == 1
    assert latest.status_code == 200
    assert latest.json()["id"] == first.json()["run_id"]


def test_inline_start_returns_the_failed_run_instead_of_bare_http_500(
    tmp_path: Path,
) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'failure.db').as_posix()}",
        task_mode="inline",
        storage_root=tmp_path / "files",
        model_provider=FailingProvider(),
        literature_adapters=[FakeLiteratureAdapter([])],
        dataset_adapters=[FakeDatasetAdapter([], b"")],
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        project_id = make_project(client)
        started = client.post(f"/api/v1/projects/{project_id}/autonomous-runs", json={})

        assert started.status_code == 202
        assert started.json()["status"] == "failed"
        run = client.get(
            f"/api/v1/autonomous-runs/{started.json()['run_id']}"
        ).json()
        assert run["status"] == "failed"
        assert run["error"]["type"] == "RuntimeError"
        assert run["error"]["message"] == "model service unavailable"


def test_startup_construction_error_never_leaves_a_planning_zombie(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'construction.db').as_posix()}",
        task_mode="inline",
        literature_adapters=[FakeLiteratureAdapter([])],
        dataset_adapters=[FakeDatasetAdapter([], b"")],
    )

    def fail_to_construct(*args, **kwargs):
        del args, kwargs
        raise ValueError("invalid runtime configuration")

    monkeypatch.setattr(routes, "autonomous_orchestrator", fail_to_construct)
    with TestClient(app, raise_server_exceptions=False) as client:
        project_id = make_project(client)
        started = client.post(f"/api/v1/projects/{project_id}/autonomous-runs", json={})

        assert started.status_code == 202
        assert started.json()["status"] == "failed"
        run = client.get(
            f"/api/v1/autonomous-runs/{started.json()['run_id']}"
        ).json()
        assert run["error"] == {
            "type": "ValueError",
            "message": "invalid runtime configuration",
            "node": "planning",
        }


def test_app_disposes_database_engine_and_exposes_readiness(tmp_path: Path) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'lifecycle.db').as_posix()}",
        task_mode="inline",
        literature_adapters=[FakeLiteratureAdapter([])],
        dataset_adapters=[FakeDatasetAdapter([], b"")],
    )
    disposed: list[bool] = []

    with TestClient(app) as client:
        engine = app.state.database_engine
        event.listen(engine, "engine_disposed", lambda _engine: disposed.append(True))
        readiness = client.get("/health/ready")
        assert readiness.status_code == 200
        assert readiness.json() == {
            "status": "ready",
            "database": "ok",
            "model_provider": "fallback",
            "task_mode": "inline",
        }

    assert disposed == [True]


def test_readiness_reports_database_failure(tmp_path: Path, monkeypatch) -> None:
    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'not-ready.db').as_posix()}",
        task_mode="inline",
        literature_adapters=[FakeLiteratureAdapter([])],
        dataset_adapters=[FakeDatasetAdapter([], b"")],
    )

    with TestClient(app) as client:
        def fail_to_connect():
            raise OSError("database offline")

        monkeypatch.setattr(app.state.database_engine, "connect", fail_to_connect)
        readiness = client.get("/health/ready")

    assert readiness.status_code == 503
    assert readiness.json()["detail"] == {
        "status": "not_ready",
        "database": "unavailable",
    }


def test_managed_worker_session_disposes_its_engine(tmp_path: Path) -> None:
    disposed: list[bool] = []
    url = f"sqlite+pysqlite:///{(tmp_path / 'worker.db').as_posix()}"

    with managed_session(url) as session:
        engine = session.get_bind()
        event.listen(engine, "engine_disposed", lambda _engine: disposed.append(True))
        session.execute(text("SELECT 1"))

    assert disposed == [True]


def test_example_environment_never_contains_a_dashscope_secret() -> None:
    example = (Path(__file__).parents[2] / ".env.example").read_text(encoding="utf-8")
    line = next(item for item in example.splitlines() if item.startswith("DASHSCOPE_API_KEY="))
    assert line == "DASHSCOPE_API_KEY="


def test_compose_waits_for_api_readiness_before_starting_web() -> None:
    compose_path = Path(__file__).parents[2] / "compose.yaml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    api = compose["services"]["api"]
    assert "/health/ready" in " ".join(api["healthcheck"]["test"])
    assert compose["services"]["web"]["depends_on"]["api"] == {
        "condition": "service_healthy"
    }


def test_repository_test_script_enforces_lint_and_backend_coverage() -> None:
    script_path = Path(__file__).parents[2] / "scripts" / "test.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert '-m ruff check edusci tests' in script
    assert '--cov=edusci' in script
    assert '--cov-fail-under=85' in script
    assert '-W error::ResourceWarning' in script
    assert 'security-check.ps1' in script
    assert 'eval-quality.ps1' in script


def test_repository_security_script_scans_worktree_and_git_history() -> None:
    script_path = Path(__file__).parents[2] / "scripts" / "security-check.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert "git grep" in script
    assert "git rev-list" in script
    assert "DASHSCOPE_API_KEY" in script
    assert "sk-[A-Za-z0-9_-]" in script


def test_quality_script_runs_the_offline_evaluation_by_default() -> None:
    script_path = Path(__file__).parents[2] / "scripts" / "eval-quality.ps1"
    script = script_path.read_text(encoding="utf-8")

    assert 'ValidateSet("Offline", "LiveQwen")' in script
    assert "edusci.evaluation" in script
    assert "quality-report.json" in script
    assert "Get-Content $EnvFile" in script
