from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy.orm import Session

from edusci.analysis.storage import LocalObjectStore
from edusci.domain.flow import FlowStage
from edusci.memory.models import DocumentChunk, DocumentRecord, EvidenceCard, Project


def _chunks(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts: list[str] = []
    start = 0
    while start < len(cleaned):
        parts.append(cleaned[start : start + size])
        if start + size >= len(cleaned):
            break
        start += size - overlap
    return parts


def ingest_pdf(
    session: Session,
    store: LocalObjectStore,
    project: Project,
    file_name: str,
    content: bytes,
) -> dict:
    if project.stage != FlowStage.EVIDENCE.value:
        raise HTTPException(status_code=409, detail="仅证据构建阶段可以摄入文献")
    try:
        path = store.save_pdf(project.id, file_name, content)
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF 解析失败: {exc}") from exc

    document = DocumentRecord(
        project_id=project.id,
        file_name=Path(file_name).name,
        storage_path=str(path),
        content_hash=hashlib.sha256(content).hexdigest(),
        page_count=len(reader.pages),
        parse_status="parsed",
    )
    session.add(document)
    session.flush()
    chunk_count = 0
    for page_index, page in enumerate(reader.pages, start=1):
        for ordinal, text in enumerate(_chunks(page.extract_text() or ""), start=1):
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            session.add(
                DocumentChunk(
                    document_id=document.id,
                    project_id=project.id,
                    page_number=page_index,
                    ordinal=ordinal,
                    text=text,
                    content_hash=digest,
                )
            )
            if chunk_count < 5:
                session.add(
                    EvidenceCard(
                        project_id=project.id,
                        title=document.file_name,
                        source_type="uploaded_pdf",
                        source_url=f"document://{document.id}",
                        locator=f"第 {page_index} 页，第 {ordinal} 块",
                        excerpt=text,
                        claim=text,
                        content_hash=digest,
                        trust_status="PASS",
                    )
                )
            chunk_count += 1
    session.commit()
    session.refresh(document)
    return {
        "id": document.id,
        "project_id": document.project_id,
        "file_name": document.file_name,
        "content_hash": document.content_hash,
        "page_count": document.page_count,
        "parse_status": document.parse_status,
        "chunk_count": chunk_count,
    }
