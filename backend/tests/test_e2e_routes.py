from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edusci.app import create_app


def sources(count: int) -> list[dict]:
    return [
        {
            "title": f"可核验研究资料 {index + 1}",
            "source_type": "journal" if index % 2 == 0 else "report",
            "url": f"https://example.edu/source/{index + 1}",
            "locator": f"第 {index + 1} 节",
            "excerpt": f"这是支持研究问题的第 {index + 1} 条可核验事实证据。",
            "verified": True,
        }
        for index in range(count)
    ]


@pytest.mark.parametrize(
    ("idea", "source_count", "route"),
    [
        ("人口变化对基础教育资源配置的影响", 5, "A"),
        ("分析大学生 AI 焦虑度与专业的关系", 1, "B"),
        ("算法透明度与组织文化的理论关系", 5, "C"),
        ("人吃饭速度与眨眼频率的关系", 0, "D"),
    ],
)
def test_all_four_routes_are_reachable(
    tmp_path: Path, idea: str, source_count: int, route: str
) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / f'{route}.db').as_posix()}"
    with TestClient(create_app(database_url=database_url, storage_root=tmp_path / route)) as client:
        project_id = client.post(
            "/api/v1/projects", json={"title": f"路径 {route}", "idea_text": idea}
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")
        client.post(
            f"/api/v1/projects/{project_id}/evidence-runs",
            json={"sources": sources(source_count)},
        )
        client.post(f"/api/v1/projects/{project_id}/gate-runs")

        snapshot = client.get(f"/api/v1/projects/{project_id}").json()
        assert snapshot["suggested_route"] == route

        client.post(
            f"/api/v1/projects/{project_id}/route-confirmations",
            json={"route": route},
        )
        client.post(f"/api/v1/projects/{project_id}/study-design-runs")

        if route in {"A", "B"}:
            csv_content = "专业,AI焦虑得分\n教育学,2.1\n教育学,2.4\n计算机,4.1\n计算机,4.5\n"
            dataset = client.post(
                f"/api/v1/projects/{project_id}/datasets",
                files={
                    "file": (
                        "demo.csv",
                        BytesIO(csv_content.encode("utf-8-sig")),
                        "text/csv",
                    )
                },
            )
            assert dataset.status_code == 201
            analysis = client.post(
                f"/api/v1/projects/{project_id}/analysis-runs",
                json={
                    "dataset_id": dataset.json()["id"],
                    "outcome_column": "AI焦虑得分",
                    "group_column": "专业",
                },
            )
            assert analysis.status_code == 202

        report = client.post(f"/api/v1/projects/{project_id}/report-runs")
        assert report.status_code == 202
        review = client.post(f"/api/v1/projects/{project_id}/review-runs")
        assert review.status_code == 202

        finished = client.get(f"/api/v1/projects/{project_id}").json()
        assert finished["report"]["result_kind"] == (
            "observed" if route in {"A", "B"} else "expected_only"
        )
        assert finished["stage"] == ("BLOCKED" if route == "D" else "COMPLETED")
