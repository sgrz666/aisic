from io import BytesIO
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from edusci.analysis.engine import analyze_dataframe, profile_dataframe
from edusci.app import create_app


def test_profile_dataframe_reports_missing_duplicates_and_pii() -> None:
    frame = pd.DataFrame(
        {
            "学号": ["001", "001", "003"],
            "专业": ["教育学", "教育学", "计算机"],
            "AI焦虑得分": [3.2, 3.2, None],
        }
    )

    profile = profile_dataframe(frame)

    assert profile["rows"] == 3
    assert profile["duplicate_rows"] == 1
    assert profile["missing_cells"] == 1
    assert profile["pii_columns"] == ["学号"]


def test_controlled_analysis_runs_group_difference_without_generated_code() -> None:
    frame = pd.DataFrame(
        {
            "专业": ["教育学", "教育学", "计算机", "计算机"],
            "AI焦虑得分": [2.0, 2.4, 4.2, 4.6],
            "技术自我效能": [4.3, 4.0, 2.1, 2.4],
        }
    )

    result = analyze_dataframe(frame, outcome_column="AI焦虑得分", group_column="专业")

    assert result["sample_size"] == 4
    assert result["group_test"]["method"] == "independent_t_test"
    assert result["group_test"]["groups"] == ["教育学", "计算机"]
    assert "generated_code" not in result
    assert result["correlations"]["AI焦虑得分"]["技术自我效能"] < 0


def _flow_to_route_b(client: TestClient) -> str:
    project_id = client.post(
        "/api/v1/projects",
        json={"title": "AI 焦虑", "idea_text": "分析大学生 AI 焦虑度与专业的关系"},
    ).json()["id"]
    client.post(f"/api/v1/projects/{project_id}/idea-runs")
    client.post(
        f"/api/v1/projects/{project_id}/evidence-runs",
        json={"sources": []},
    )
    client.post(f"/api/v1/projects/{project_id}/gate-runs")
    client.post(
        f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "B"}
    )
    return project_id


def test_route_b_generates_questionnaire_then_analyzes_uploaded_csv(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'test.db').as_posix()}"
    app = create_app(database_url=database_url, task_mode="inline", storage_root=tmp_path / "files")
    with TestClient(app) as client:
        project_id = _flow_to_route_b(client)

        design = client.post(f"/api/v1/projects/{project_id}/study-design-runs")
        assert design.status_code == 202
        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["stage"] == "WAITING_FOR_DATA"
        assert len(snapshot["study_design"]["questionnaire"]["items"]) >= 5

        csv_content = "专业,AI焦虑得分,技术自我效能\n教育学,2.0,4.3\n教育学,2.4,4.0\n计算机,4.2,2.1\n计算机,4.6,2.4\n"
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/datasets",
            files={"file": ("answers.csv", BytesIO(csv_content.encode("utf-8-sig")), "text/csv")},
        )
        assert uploaded.status_code == 201
        dataset_id = uploaded.json()["id"]
        assert uploaded.json()["quality_report"]["rows"] == 4

        analysis = client.post(
            f"/api/v1/projects/{project_id}/analysis-runs",
            json={
                "dataset_id": dataset_id,
                "outcome_column": "AI焦虑得分",
                "group_column": "专业",
            },
        )
        assert analysis.status_code == 202
        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["stage"] == "S5_REPORT"
        assert snapshot["analysis_result"]["sample_size"] == 4


def test_route_a_accepts_existing_dataset_from_analysis_stage(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'route-a.db').as_posix()}"
    app = create_app(database_url=database_url, task_mode="inline", storage_root=tmp_path / "files")
    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "教育资源", "idea_text": "人口变化对基础教育资源配置的影响"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(
            f"/api/v1/projects/{project_id}/evidence-runs",
            json={
                "sources": [
                    {
                        "title": f"教育统计资料 {index}",
                        "source_type": "report" if index % 2 else "journal",
                        "url": f"https://example.edu/{index}",
                        "locator": f"第 {index} 节",
                        "excerpt": "学龄人口变化会影响学校布局与教师配置。",
                        "verified": True,
                    }
                    for index in range(5)
                ]
            },
        )
        client.post(f"/api/v1/projects/{project_id}/gate-runs")
        client.post(f"/api/v1/projects/{project_id}/route-confirmations", json={"route": "A"})
        client.post(f"/api/v1/projects/{project_id}/study-design-runs")
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S4_ANALYSIS"

        csv_content = "地区,学龄人口,学校数\n甲,1200,12\n乙,900,9\n"
        uploaded = client.post(
            f"/api/v1/projects/{project_id}/datasets",
            files={"file": ("public-data.csv", BytesIO(csv_content.encode("utf-8-sig")), "text/csv")},
        )

        assert uploaded.status_code == 201
        assert client.get(f"/api/v1/projects/{project_id}").json()["stage"] == "S4_ANALYSIS"
