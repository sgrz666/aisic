from __future__ import annotations

import hashlib
import io
import re
import time
from collections.abc import Callable

from bs4 import BeautifulSoup
from pydantic import BaseModel, Field
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.autonomy.contracts import DeepResearchLimits, EvidenceStance
from edusci.memory.models import (
    ClaimEvidenceLinkRecord,
    ProjectEvidenceUseRecord,
    ResearchChunkRecord,
    ResearchClaimRecord,
    ResearchDocumentRecord,
    ResearchDocumentVersionRecord,
    ResearchIterationRecord,
)


def _hash(value: str | bytes) -> str:
    data = value if isinstance(value, bytes) else value.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class FullTextArtifact(BaseModel):
    url: str
    mime_type: str
    content: bytes
    license_name: str = ""
    license_url: str = ""


class ParsedChunk(BaseModel):
    index: int
    locator: str
    text: str


class ExtractedClaim(BaseModel):
    statement: str = Field(min_length=5)
    stance: EvidenceStance
    confidence: int = Field(ge=0, le=100)


class ClaimBatch(BaseModel):
    claims: list[ExtractedClaim] = Field(default_factory=list, max_length=20)


class DeepResearchResult(BaseModel):
    iterations: int
    source_count: int
    fulltext_count: int
    claim_count: int
    coverage: int
    counter_evidence_coverage: int
    stop_reason: str
    gaps: list[str] = Field(default_factory=list)
    degraded_sources: list[str] = Field(default_factory=list)
    model_usage: dict = Field(default_factory=dict)


class FullTextParser:
    def parse(self, artifact: FullTextArtifact) -> list[ParsedChunk]:
        mime = artifact.mime_type.lower()
        if "pdf" in mime:
            return self._pdf(artifact.content)
        if "html" in mime:
            return self._html(artifact.content)
        text = artifact.content.decode("utf-8", errors="replace").strip()
        return [ParsedChunk(index=0, locator="全文", text=text)] if text else []

    @staticmethod
    def _pdf(content: bytes) -> list[ParsedChunk]:
        reader = PdfReader(io.BytesIO(content))
        return [
            ParsedChunk(index=index, locator=f"第 {index + 1} 页", text=text)
            for index, page in enumerate(reader.pages)
            if (text := (page.extract_text() or "").strip())
        ]

    @staticmethod
    def _html(content: bytes) -> list[ParsedChunk]:
        soup = BeautifulSoup(content, "html.parser")
        chunks: list[ParsedChunk] = []
        current_heading = "正文"
        current_text: list[str] = []

        def flush() -> None:
            text = "\n".join(current_text).strip()
            if text:
                chunks.append(
                    ParsedChunk(index=len(chunks), locator=current_heading, text=text)
                )
            current_text.clear()

        for node in soup.find_all(["h1", "h2", "h3", "p", "li"]):
            value = node.get_text(" ", strip=True)
            if not value:
                continue
            if node.name in {"h1", "h2", "h3"}:
                flush()
                current_heading = value[:200]
            else:
                current_text.append(value)
        flush()
        return chunks


class DeepResearchEngine:
    def __init__(
        self,
        *,
        session: Session,
        provider,
        search: Callable[[list[str], int], list[dict]],
        fetch_fulltext: Callable[[dict], FullTextArtifact | None],
        parser: FullTextParser | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.search = search
        self.fetch_fulltext = fetch_fulltext
        self.parser = parser or FullTextParser()

    @staticmethod
    def _canonical_key(candidate: dict) -> str:
        doi = str(candidate.get("doi") or "").strip().lower()
        return f"doi:{doi}" if doi else f"url:{str(candidate['url']).strip()}"

    @staticmethod
    def _license_allows(candidate: dict) -> bool:
        value = " ".join(
            [
                str(candidate.get("license_name") or ""),
                str(candidate.get("license_url") or ""),
            ]
        ).lower()
        return any(token in value for token in ("cc by", "creative commons", "public domain"))

    def _document(self, candidate: dict) -> ResearchDocumentRecord:
        key = self._canonical_key(candidate)
        document = self.session.scalar(
            select(ResearchDocumentRecord).where(
                ResearchDocumentRecord.canonical_key == key
            )
        )
        if document is None:
            document = ResearchDocumentRecord(
                canonical_key=key,
                title=str(candidate.get("title") or "未命名来源"),
                source_type=str(candidate.get("source") or "scholarly"),
                canonical_url=str(candidate["url"]),
                bibliographic={
                    key: candidate[key]
                    for key in ("doi", "authors", "year", "source_title")
                    if candidate.get(key)
                },
                license_name=str(candidate.get("license_name") or ""),
                license_url=str(candidate.get("license_url") or ""),
            )
            self.session.add(document)
            self.session.flush()
        return document

    def _persist_artifact(
        self, document: ResearchDocumentRecord, artifact: FullTextArtifact
    ) -> list[ResearchChunkRecord]:
        content_hash = _hash(artifact.content)
        version = self.session.scalar(
            select(ResearchDocumentVersionRecord).where(
                ResearchDocumentVersionRecord.document_id == document.id,
                ResearchDocumentVersionRecord.content_hash == content_hash,
            )
        )
        if version is None:
            parsed = self.parser.parse(artifact)
            version = ResearchDocumentVersionRecord(
                document_id=document.id,
                content_hash=content_hash,
                mime_type=artifact.mime_type,
                storage_path=artifact.url,
                locator_index={str(item.index): item.locator for item in parsed},
            )
            self.session.add(version)
            self.session.flush()
            chunks = [
                ResearchChunkRecord(
                    version_id=version.id,
                    chunk_index=item.index,
                    locator=item.locator,
                    text=item.text,
                    text_hash=_hash(item.text),
                )
                for item in parsed
                if item.text.strip()
            ]
            self.session.add_all(chunks)
            self.session.flush()
            return chunks
        return list(
            self.session.scalars(
                select(ResearchChunkRecord)
                .where(ResearchChunkRecord.version_id == version.id)
                .order_by(ResearchChunkRecord.chunk_index)
            )
        )

    def _extract(
        self,
        *,
        run_id: str,
        project_id: str,
        chunk: ResearchChunkRecord,
    ) -> int:
        payload = self.provider.complete_json(
            "extractor",
            [
                {
                    "role": "system",
                    "content": (
                        "从给定全文片段提取可核验的原子观点。只能使用片段内容；"
                        "stance 为 supports、counter 或 qualifies。只返回 JSON。"
                    ),
                },
                {"role": "user", "content": chunk.text},
            ],
            schema=ClaimBatch,
        )
        batch = ClaimBatch.model_validate(payload)
        count = 0
        for extracted in batch.claims:
            normalized = re.sub(r"\s+", " ", extracted.statement).strip().lower()
            claim_hash = _hash(normalized)
            claim = self.session.scalar(
                select(ResearchClaimRecord).where(
                    ResearchClaimRecord.claim_hash == claim_hash
                )
            )
            if claim is None:
                claim = ResearchClaimRecord(
                    claim_hash=claim_hash,
                    statement=extracted.statement,
                )
                self.session.add(claim)
                self.session.flush()
            link = self.session.scalar(
                select(ClaimEvidenceLinkRecord).where(
                    ClaimEvidenceLinkRecord.claim_id == claim.id,
                    ClaimEvidenceLinkRecord.chunk_id == chunk.id,
                    ClaimEvidenceLinkRecord.stance == extracted.stance.value,
                )
            )
            if link is None:
                self.session.add(
                    ClaimEvidenceLinkRecord(
                        claim_id=claim.id,
                        chunk_id=chunk.id,
                        stance=extracted.stance.value,
                        excerpt_hash=chunk.text_hash,
                        confidence=extracted.confidence,
                    )
                )
            use = self.session.scalar(
                select(ProjectEvidenceUseRecord).where(
                    ProjectEvidenceUseRecord.project_id == project_id,
                    ProjectEvidenceUseRecord.claim_id == claim.id,
                )
            )
            if use is None:
                self.session.add(
                    ProjectEvidenceUseRecord(
                        project_id=project_id,
                        run_id=run_id,
                        claim_id=claim.id,
                        assessment={"status": "candidate"},
                    )
                )
            count += 1
        self.session.flush()
        return count

    def _metrics(self, project_id: str) -> tuple[int, int, int]:
        uses = list(
            self.session.scalars(
                select(ProjectEvidenceUseRecord).where(
                    ProjectEvidenceUseRecord.project_id == project_id
                )
            )
        )
        if not uses:
            return 0, 0, 0
        claim_ids = [item.claim_id for item in uses]
        links = list(
            self.session.scalars(
                select(ClaimEvidenceLinkRecord).where(
                    ClaimEvidenceLinkRecord.claim_id.in_(claim_ids)
                )
            )
        )
        by_claim: dict[str, set[str]] = {claim_id: set() for claim_id in claim_ids}
        for link in links:
            by_claim[link.claim_id].add(link.stance)
        covered = sum(bool(stances) for stances in by_claim.values())
        countered = sum(EvidenceStance.COUNTER.value in stances for stances in by_claim.values())
        total = len(by_claim)
        return total, round(100 * covered / total), round(100 * countered / total)

    def run(
        self,
        *,
        run_id: str,
        project_id: str,
        seed_queries: list[str],
        subquestions: list[str],
        limits: DeepResearchLimits,
    ) -> DeepResearchResult:
        started = time.monotonic()
        queries = list(dict.fromkeys(seed_queries))
        seen: set[str] = set()
        degraded: list[str] = []
        fulltext_count = 0
        iteration = 0
        stop_reason = "max_budget"
        gaps = list(subquestions)

        for iteration in range(1, limits.max_rounds + 1):
            timeout = limits.hard_timeout_minutes * 60
            if time.monotonic() - started >= timeout:
                stop_reason = "hard_timeout"
                break
            candidates = self.search(queries, iteration)
            cap = (
                limits.initial_fulltexts
                if iteration <= limits.initial_rounds
                else limits.max_fulltexts
            )
            for candidate in candidates:
                key = self._canonical_key(candidate)
                if key in seen:
                    continue
                seen.add(key)
                document = self._document(candidate)
                if fulltext_count >= cap or not self._license_allows(candidate):
                    continue
                try:
                    artifact = self.fetch_fulltext(candidate)
                except Exception as exc:
                    degraded.append(f"{candidate.get('source', 'source')}: {exc}")
                    continue
                if artifact is None:
                    continue
                chunks = self._persist_artifact(document, artifact)
                for chunk in chunks:
                    self._extract(
                        run_id=run_id,
                        project_id=project_id,
                        chunk=chunk,
                    )
                fulltext_count += 1

            claim_count, coverage, counter_coverage = self._metrics(project_id)
            saturated = (
                fulltext_count >= 2
                and claim_count > 0
                and coverage == 100
                and counter_coverage == 100
            )
            gaps = [] if saturated else ["缺少独立反证或限定性证据"]
            self.session.add(
                ResearchIterationRecord(
                    run_id=run_id,
                    iteration=iteration,
                    queries=queries,
                    metrics={
                        "sources": len(seen),
                        "fulltexts": fulltext_count,
                        "claims": claim_count,
                        "coverage": coverage,
                        "counter_evidence_coverage": counter_coverage,
                    },
                    gaps=gaps,
                    stop_reason="evidence_saturated" if saturated else "",
                )
            )
            self.session.commit()
            if saturated:
                stop_reason = "evidence_saturated"
                break
            queries = list(
                dict.fromkeys(
                    [
                        *seed_queries,
                        *[
                            f"{query} counter evidence contradiction null result"
                            for query in seed_queries
                        ],
                    ]
                )
            )

        claim_count, coverage, counter_coverage = self._metrics(project_id)
        return DeepResearchResult(
            iterations=iteration,
            source_count=len(seen),
            fulltext_count=fulltext_count,
            claim_count=claim_count,
            coverage=coverage,
            counter_evidence_coverage=counter_coverage,
            stop_reason=stop_reason,
            gaps=gaps,
            degraded_sources=degraded,
            model_usage=dict(getattr(self.provider, "usage", {})),
        )
