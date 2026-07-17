from __future__ import annotations

import json
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.memory.models import (
    AutonomousRunRecord,
    ClaimEvidenceLinkRecord,
    Project,
    ProjectEvidenceUseRecord,
    ResearchChunkRecord,
    ResearchClaimRecord,
    ResearchDocumentRecord,
    ResearchDocumentVersionRecord,
    ReportArtifactRecord,
)
from edusci.services.reporting_v2 import regenerate_report_v2


class _ReportRevision(BaseModel):
    abstract: str = Field(min_length=20)
    limitation_note: str = Field(min_length=5)


def _confidence(links: list[dict]) -> str:
    supporting_documents = {
        item["document_id"] for item in links if item["stance"] == "supports"
    }
    has_counter = any(item["stance"] == "counter" for item in links)
    if len(supporting_documents) >= 2 and not has_counter:
        return "high"
    if supporting_documents:
        return "moderate"
    return "low"


def regenerate_report_v3(
    session: Session,
    project: Project,
    *,
    refresh_evidence: bool = True,
    model_provider=None,
    planner=None,
    literature_scout=None,
) -> ReportArtifactRecord:
    artifact = regenerate_report_v2(
        session,
        project,
        refresh_evidence=refresh_evidence,
        model_provider=model_provider,
        planner=planner,
        literature_scout=literature_scout,
    )
    run = session.scalar(
        select(AutonomousRunRecord)
        .where(AutonomousRunRecord.project_id == project.id)
        .order_by(AutonomousRunRecord.created_at.desc())
    )
    uses = []
    if run is not None:
        uses = list(
            session.scalars(
                select(ProjectEvidenceUseRecord).where(
                    ProjectEvidenceUseRecord.run_id == run.id
                )
            )
        )
    claim_ids = [item.claim_id for item in uses]
    claims = {
        item.id: item
        for item in session.scalars(
            select(ResearchClaimRecord).where(ResearchClaimRecord.id.in_(claim_ids))
        )
    } if claim_ids else {}
    links = list(
        session.scalars(
            select(ClaimEvidenceLinkRecord).where(
                ClaimEvidenceLinkRecord.claim_id.in_(claim_ids)
            )
        )
    ) if claim_ids else []
    chunk_ids = [item.chunk_id for item in links]
    chunks = {
        item.id: item
        for item in session.scalars(
            select(ResearchChunkRecord).where(ResearchChunkRecord.id.in_(chunk_ids))
        )
    } if chunk_ids else {}
    version_ids = [chunk.version_id for chunk in chunks.values()]
    versions = {
        item.id: item
        for item in session.scalars(
            select(ResearchDocumentVersionRecord).where(
                ResearchDocumentVersionRecord.id.in_(version_ids)
            )
        )
    } if version_ids else {}
    document_ids = [version.document_id for version in versions.values()]
    documents = {
        item.id: item
        for item in session.scalars(
            select(ResearchDocumentRecord).where(
                ResearchDocumentRecord.id.in_(document_ids)
            )
        )
    } if document_ids else {}

    evidence_ledger: list[dict] = []
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for link in links:
        chunk = chunks.get(link.chunk_id)
        if chunk is None or not chunk.locator.strip() or not chunk.text.strip():
            continue
        version = versions[chunk.version_id]
        document = documents[version.document_id]
        item = {
            "evidence_id": link.id,
            "claim_id": link.claim_id,
            "stance": link.stance,
            "confidence": link.confidence,
            "locator": chunk.locator,
            "excerpt": chunk.text,
            "document_id": document.id,
            "document_title": document.title,
            "source_url": document.canonical_url,
            "license_name": document.license_name,
        }
        evidence_ledger.append(item)
        by_claim[link.claim_id].append(item)

    conclusions = []
    conflicts = []
    claim_ledger = []
    for claim_id, claim in claims.items():
        claim_links = by_claim.get(claim_id, [])
        supporting = [item["evidence_id"] for item in claim_links if item["stance"] == "supports"]
        counter = [item["evidence_id"] for item in claim_links if item["stance"] == "counter"]
        qualifying = [item["evidence_id"] for item in claim_links if item["stance"] == "qualifies"]
        claim_ledger.append(
            {
                "claim_id": claim_id,
                "statement": claim.statement,
                "supports": supporting,
                "counter": counter,
                "qualifies": qualifying,
            }
        )
        if supporting:
            conclusions.append(
                {
                    "claim_id": claim_id,
                    "statement": claim.statement,
                    "confidence": _confidence(claim_links),
                    "evidence_ids": [item["evidence_id"] for item in claim_links],
                }
            )
        if supporting and counter:
            conflicts.append(
                {
                    "claim_id": claim_id,
                    "statement": claim.statement,
                    "supporting_evidence_ids": supporting,
                    "counter_evidence_ids": counter,
                }
            )

    report = dict(artifact.report_json)
    report.update(
        {
            "schema_version": 3,
            "research_methodology": {
                "depth_mode": (run.config or {}).get("depth_mode", "adaptive_deep") if run else "adaptive_deep",
                "iterations": run.current_iteration if run else 0,
                "sources_considered": run.source_count if run else 0,
                "fulltexts_parsed": run.fulltext_count if run else 0,
                "coverage": run.coverage if run else 0,
                "counter_evidence_coverage": run.counter_evidence_coverage if run else 0,
                "stop_reason": run.stop_reason if run else "no_deep_research_run",
            },
            "claim_ledger": claim_ledger,
            "evidence_ledger": evidence_ledger,
            "evidence_synthesis": {
                "supported_claim_count": len(conclusions),
                "conflicting_claim_count": len(conflicts),
            },
            "conflicting_evidence": conflicts,
            "conclusions": conclusions,
            "restricted": not bool(conclusions),
        }
    )
    review = dict(artifact.review_json)
    checks = dict(review.get("checks") or {})
    checks["claim_grounding"] = {
        "status": "PASS" if conclusions else "WARN",
        "message": (
            "所有进入结论的观点均绑定片段定位"
            if conclusions
            else "没有可定位证据支持的结论；报告已限制为方法、证据缺口和研究建议"
        ),
    }
    review.update(
        {
            "schema_version": 3,
            "checks": checks,
            "overall": review.get("overall", "WARN"),
            "revision_round": 0,
        }
    )
    if model_provider is not None:
        try:
            agent_review = model_provider.complete_json(
                "review",
                [
                    {
                        "role": "system",
                        "content": "独立审查证据矩阵与报告，只返回JSON建议，不得新增事实或引用。",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "question": project.idea_text,
                                "claims": claim_ledger,
                                "evidence": evidence_ledger,
                                "conclusions": conclusions,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
            )
            review["agent_review"] = agent_review
            revision_round = 0
            while (
                str(agent_review.get("status", "PASS")).upper() in {"WARN", "BLOCK"}
                and revision_round < 2
            ):
                revision = model_provider.complete_json(
                    "synthesis",
                    [
                        {
                            "role": "system",
                            "content": (
                                "根据独立复审建议修订摘要和限制说明。不得增加证据矩阵中没有的事实、"
                                "引用或统计量，只返回JSON。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "abstract": report.get("abstract", ""),
                                    "review": agent_review,
                                    "conclusions": conclusions,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                    schema=_ReportRevision,
                )
                report["abstract"] = revision["abstract"]
                report.setdefault("revision_notes", []).append(
                    revision["limitation_note"]
                )
                revision_round += 1
                agent_review = model_provider.complete_json(
                    "review",
                    [
                        {
                            "role": "system",
                            "content": "复核修订后的摘要是否仍严格受证据矩阵约束，只返回JSON。",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "abstract": report["abstract"],
                                    "claims": claim_ledger,
                                    "evidence": evidence_ledger,
                                },
                                ensure_ascii=False,
                            ),
                        },
                    ],
                )
            review["agent_review"] = agent_review
            review["revision_round"] = revision_round
        except Exception as exc:
            review["agent_review"] = {"status": "unavailable", "message": str(exc)}

    artifact.schema_version = 3
    artifact.report_json = report
    artifact.review_json = review
    artifact.generation_config = {
        **artifact.generation_config,
        "deep_research": True,
        "max_revision_rounds": 2,
    }
    project.report = report
    project.review = review
    session.add_all([artifact, project])
    session.commit()
    session.refresh(artifact)
    return artifact
