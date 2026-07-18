from __future__ import annotations

import hashlib
import io
import json
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
    ResearchClaimSubquestionRecord,
    ResearchDocumentRecord,
    ResearchDocumentVersionRecord,
    ResearchIterationRecord,
    ResearchSubquestionRecord,
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
    excerpt: str = ""
    subquestion_index: int = Field(default=0, ge=0)
    claim_type: str = "finding"


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
    quality_metrics: dict = Field(default_factory=dict)
    quality_gate_status: str = "LIMITED"


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
        memory_index=None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.search = search
        self.fetch_fulltext = fetch_fulltext
        self.parser = parser or FullTextParser()
        self.memory_index = memory_index

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
        subquestions: list[ResearchSubquestionRecord],
    ) -> int:
        payload = self.provider.complete_json(
            "extractor",
            [
                {
                    "role": "system",
                    "content": (
                        "从给定全文片段提取可核验的原子观点。只能使用片段内容；"
                        "excerpt 必须逐字复制原文中的连续片段；subquestion_index 必须指向"
                        "给定子问题；stance 为 supports、counter 或 qualifies。只返回 JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "subquestions": [item.question for item in subquestions],
                            "chunk": chunk.text,
                        },
                        ensure_ascii=False,
                    ),
                },
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
                    claim_type=extracted.claim_type,
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
            provided_excerpt = extracted.excerpt.strip()
            excerpt = provided_excerpt or chunk.text
            exact_grounded = bool(excerpt and excerpt in chunk.text)
            validation_status = "validated" if exact_grounded else "rejected"
            entailment_score = extracted.confidence if exact_grounded else 0
            validator_model = "deterministic_exact_quote"
            if exact_grounded and hasattr(self.provider, "verify_evidence"):
                try:
                    verification = self.provider.verify_evidence(
                        statement=extracted.statement,
                        excerpt=excerpt,
                        stance=extracted.stance.value,
                    )
                    validation_status = str(verification["status"])
                    if verification["stance"] != extracted.stance.value:
                        validation_status = "rejected"
                    entailment_score = int(verification["entailment_score"])
                    validator_model = str(
                        getattr(self.provider, "generation_model", "qwen-verifier")
                    )
                except Exception:
                    validation_status = "unverified"
                    entailment_score = 0
                    validator_model = "qwen_verifier_unavailable"
            if link is None:
                link = ClaimEvidenceLinkRecord(
                    claim_id=claim.id,
                    chunk_id=chunk.id,
                    stance=extracted.stance.value,
                    excerpt=excerpt,
                    excerpt_hash=_hash(excerpt),
                    confidence=extracted.confidence,
                    validation_status=validation_status,
                    entailment_score=entailment_score,
                    validator_model=validator_model,
                )
                self.session.add(link)
            else:
                validation_status = link.validation_status
            subquestion = subquestions[
                min(extracted.subquestion_index, len(subquestions) - 1)
            ]
            binding = self.session.scalar(
                select(ResearchClaimSubquestionRecord).where(
                    ResearchClaimSubquestionRecord.subquestion_id == subquestion.id,
                    ResearchClaimSubquestionRecord.claim_id == claim.id,
                )
            )
            if binding is None:
                self.session.add(
                    ResearchClaimSubquestionRecord(
                        subquestion_id=subquestion.id,
                        claim_id=claim.id,
                        relevance_score=extracted.confidence,
                        status=(
                            "accepted"
                            if validation_status == "validated"
                            else "rejected"
                        ),
                    )
                )
            use = self.session.scalar(
                select(ProjectEvidenceUseRecord).where(
                    ProjectEvidenceUseRecord.project_id == project_id,
                    ProjectEvidenceUseRecord.claim_id == claim.id,
                )
            )
            if use is None and validation_status == "validated":
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

    def _ensure_subquestions(
        self, run_id: str, questions: list[str]
    ) -> list[ResearchSubquestionRecord]:
        existing = list(
            self.session.scalars(
                select(ResearchSubquestionRecord)
                .where(ResearchSubquestionRecord.run_id == run_id)
                .order_by(ResearchSubquestionRecord.ordinal)
            )
        )
        if existing:
            return existing
        records = [
            ResearchSubquestionRecord(
                run_id=run_id,
                ordinal=index,
                question=question,
                required=True,
            )
            for index, question in enumerate(questions or ["General research question"])
        ]
        self.session.add_all(records)
        self.session.flush()
        return records

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

    def _quality_metrics(
        self, run_id: str, *, counter_search_completed: bool
    ) -> dict[str, int]:
        subquestions = list(
            self.session.scalars(
                select(ResearchSubquestionRecord).where(
                    ResearchSubquestionRecord.run_id == run_id,
                    ResearchSubquestionRecord.required.is_(True),
                )
            )
        )
        subquestion_ids = [item.id for item in subquestions]
        bindings = (
            list(
                self.session.scalars(
                    select(ResearchClaimSubquestionRecord).where(
                        ResearchClaimSubquestionRecord.subquestion_id.in_(
                            subquestion_ids
                        ),
                        ResearchClaimSubquestionRecord.status == "accepted",
                    )
                )
            )
            if subquestion_ids
            else []
        )
        claim_ids = list({item.claim_id for item in bindings})
        links = (
            list(
                self.session.scalars(
                    select(ClaimEvidenceLinkRecord).where(
                        ClaimEvidenceLinkRecord.claim_id.in_(claim_ids)
                    )
                )
            )
            if claim_ids
            else []
        )
        validated = [item for item in links if item.validation_status == "validated"]
        chunk_ids = [item.chunk_id for item in validated]
        chunks = {
            item.id: item
            for item in self.session.scalars(
                select(ResearchChunkRecord).where(ResearchChunkRecord.id.in_(chunk_ids))
            )
        } if chunk_ids else {}
        version_ids = [item.version_id for item in chunks.values()]
        versions = {
            item.id: item
            for item in self.session.scalars(
                select(ResearchDocumentVersionRecord).where(
                    ResearchDocumentVersionRecord.id.in_(version_ids)
                )
            )
        } if version_ids else {}
        claim_documents: dict[str, set[str]] = {claim_id: set() for claim_id in claim_ids}
        counter_claims: set[str] = set()
        for link in validated:
            chunk = chunks.get(link.chunk_id)
            version = versions.get(chunk.version_id) if chunk else None
            if version is not None:
                claim_documents[link.claim_id].add(version.document_id)
            if link.stance == EvidenceStance.COUNTER.value:
                counter_claims.add(link.claim_id)

        claims_by_subquestion: dict[str, set[str]] = {
            item.id: set() for item in subquestions
        }
        for binding in bindings:
            claims_by_subquestion[binding.subquestion_id].add(binding.claim_id)
        covered = 0
        independent = 0
        counter_found = 0
        for subquestion in subquestions:
            bound_claims = claims_by_subquestion[subquestion.id]
            documents = set().union(
                *(claim_documents.get(claim_id, set()) for claim_id in bound_claims)
            ) if bound_claims else set()
            if documents:
                covered += 1
            if len(documents) >= 2:
                independent += 1
            if bound_claims.intersection(counter_claims):
                counter_found += 1
        total = len(subquestions)

        def percent(value: int) -> int:
            return round(100 * value / total) if total else 0

        return {
            "subquestion_coverage": percent(covered),
            "independent_source_coverage": percent(independent),
            "counter_search_coverage": 100 if counter_search_completed and total else 0,
            "counter_found_coverage": percent(counter_found),
            "grounding_pass_rate": (
                round(100 * len(validated) / len(links)) if links else 0
            ),
            "validated_evidence_count": len(validated),
            "accepted_claim_count": len(claim_ids),
        }

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
        counter_queries = [
            (
                f"{question} 反证 相反结果 无显著差异"
                if re.search(r"[\u3400-\u9fff]", question)
                else f"{question} counter evidence contradiction null result"
            )
            for question in subquestions
        ]
        queries = list(dict.fromkeys([*seed_queries, *counter_queries]))
        seen: set[str] = set()
        seen_memory_chunks: set[str] = set()
        degraded: list[str] = []
        fulltext_count = 0
        iteration = 0
        stop_reason = "budget_exhausted_limited"
        gaps = list(subquestions)
        subquestion_records = self._ensure_subquestions(run_id, subquestions)
        previous_evidence_count = -1
        stagnant_rounds = 0
        quality_metrics: dict[str, int] = {}

        for iteration in range(1, limits.max_rounds + 1):
            timeout = limits.hard_timeout_minutes * 60
            if time.monotonic() - started >= timeout:
                stop_reason = "hard_timeout"
                break
            if self.memory_index is not None:
                for query in queries:
                    try:
                        memory_candidates = self.memory_index.search(query, limit=20)
                    except Exception as exc:
                        degraded.append(f"research_memory: {exc}")
                        break
                    for memory_candidate in memory_candidates:
                        if memory_candidate.id in seen_memory_chunks:
                            continue
                        seen_memory_chunks.add(memory_candidate.id)
                        chunk = self.session.get(
                            ResearchChunkRecord, memory_candidate.id
                        )
                        if chunk is not None:
                            self._extract(
                                run_id=run_id,
                                project_id=project_id,
                                chunk=chunk,
                                subquestions=subquestion_records,
                            )
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
                if self.memory_index is not None:
                    self.memory_index.ensure_embeddings(chunks)
                for chunk in chunks:
                    self._extract(
                        run_id=run_id,
                        project_id=project_id,
                        chunk=chunk,
                        subquestions=subquestion_records,
                    )
                fulltext_count += 1

            quality_metrics = self._quality_metrics(
                run_id, counter_search_completed=bool(counter_queries)
            )
            claim_count = quality_metrics["accepted_claim_count"]
            coverage = quality_metrics["subquestion_coverage"]
            counter_coverage = quality_metrics["counter_search_coverage"]
            evidence_count = quality_metrics["validated_evidence_count"]
            if evidence_count > previous_evidence_count:
                stagnant_rounds = 0
            else:
                stagnant_rounds += 1
            previous_evidence_count = evidence_count
            saturated = (
                iteration >= 2
                and quality_metrics["subquestion_coverage"] == 100
                and quality_metrics["independent_source_coverage"] == 100
                and quality_metrics["counter_search_coverage"] == 100
                and quality_metrics["grounding_pass_rate"] == 100
                and stagnant_rounds >= 2
            )
            gaps = [] if saturated else ["证据尚未满足独立来源覆盖或连续两轮饱和条件"]
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
                        **quality_metrics,
                        "stagnant_rounds": stagnant_rounds,
                    },
                    gaps=gaps,
                    stop_reason="evidence_saturated" if saturated else "",
                )
            )
            self.session.commit()
            if saturated:
                stop_reason = "evidence_saturated"
                break
            queries = list(dict.fromkeys([*seed_queries, *counter_queries]))

        quality_metrics = self._quality_metrics(
            run_id, counter_search_completed=bool(counter_queries)
        )
        claim_count = quality_metrics["accepted_claim_count"]
        coverage = quality_metrics["subquestion_coverage"]
        counter_coverage = quality_metrics["counter_search_coverage"]
        quality_gate_status = (
            "PASS"
            if all(
                quality_metrics[key] == 100
                for key in (
                    "subquestion_coverage",
                    "independent_source_coverage",
                    "counter_search_coverage",
                    "grounding_pass_rate",
                )
            )
            else "LIMITED"
        )
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
            quality_metrics=quality_metrics,
            quality_gate_status=quality_gate_status,
        )
