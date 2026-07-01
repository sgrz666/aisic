from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfWriter

from edusci.app import create_app


def test_pdf_upload_is_registered_and_parsed_by_page(tmp_path: Path) -> None:
    database_url = f"sqlite+pysqlite:///{(tmp_path / 'docs.db').as_posix()}"
    app = create_app(database_url=database_url, storage_root=tmp_path / "files")
    pdf = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=400)
    writer.write(pdf)

    with TestClient(app) as client:
        project_id = client.post(
            "/api/v1/projects",
            json={"title": "文献摄入", "idea_text": "大学生学习投入与反馈的关系"},
        ).json()["id"]
        client.post(f"/api/v1/projects/{project_id}/idea-runs")

        response = client.post(
            f"/api/v1/projects/{project_id}/documents",
            files={"file": ("seed.pdf", pdf.getvalue(), "application/pdf")},
        )

        assert response.status_code == 201
        assert response.json()["file_name"] == "seed.pdf"
        assert response.json()["page_count"] == 1
        assert response.json()["parse_status"] == "parsed"
        assert response.json()["chunk_count"] == 0

