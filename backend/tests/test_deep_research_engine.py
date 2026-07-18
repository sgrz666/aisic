import json
from pathlib import Path

from sqlalchemy import select

from edusci.autonomy.contracts import DeepResearchLimits
from edusci.autonomy.deep_research import (
    DeepResearchEngine,
    FullTextArtifact,
    FullTextParser,
)
from edusci.memory.database import build_session_factory
from edusci.memory.models import (
    ClaimEvidenceLinkRecord,
    ProjectEvidenceUseRecord,
    ResearchClaimRecord,
    ResearchClaimSubquestionRecord,
    ResearchDocumentRecord,
    ResearchSubquestionRecord,
)
from edusci.memory.retrieval import ResearchMemoryIndex


def test_html_fulltext_parser_preserves_section_locator() -> None:
    artifact = FullTextArtifact(
        url="https://example.edu/report",
        mime_type="text/html",
        content=(
            b"<html><body><h1>Methods</h1><p>We surveyed 400 students.</p>"
            b"<h2>Results</h2><p>Anxiety declined after the intervention.</p></body></html>"
        ),
        license_name="CC BY 4.0",
    )

    chunks = FullTextParser().parse(artifact)

    assert [chunk.locator for chunk in chunks] == ["Methods", "Results"]
    assert "400 students" in chunks[0].text


class _Provider:
    usage = {"requests": 2, "prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40}
    embedding_model = "text-embedding-v4"
    embedding_dimension = 1024

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] + [0.0] * 1023 for _ in texts]

    def complete_json(self, role, messages, schema=None):
        raw = messages[-1]["content"]
        text = json.loads(raw)["chunk"] if raw.startswith("{") else raw
        if "declined" in text:
            payload = {
                "claims": [
                    {
                        "statement": "The intervention reduced anxiety.",
                        "stance": "counter",
                        "confidence": 86,
                        "excerpt": text,
                        "subquestion_index": 0,
                    }
                ]
            }
        else:
            payload = {
                "claims": [
                    {
                        "statement": "The intervention reduced anxiety.",
                        "stance": "supports",
                        "confidence": 82,
                        "excerpt": text,
                        "subquestion_index": 0,
                    }
                ]
            }
        return schema.model_validate(payload).model_dump(mode="json") if schema else payload


def test_deep_research_expands_budget_and_persists_counter_evidence(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'cycle.db').as_posix()}"
    )
    calls: list[list[str]] = []

    def search(queries: list[str], iteration: int) -> list[dict]:
        calls.append(queries)
        if iteration == 1:
            return [
                {
                    "source": "semantic-scholar",
                    "source_id": "paper-a",
                    "title": "Positive study",
                    "url": "https://example.edu/a",
                    "doi": "10.1/a",
                    "abstract": "A positive association was observed.",
                    "license_name": "CC BY 4.0",
                    "open_access_url": "https://example.edu/a.html",
                }
            ]
        return [
            {
                "source": "arxiv",
                "source_id": "paper-b",
                "title": "Counter study",
                "url": "https://example.edu/b",
                "doi": "10.1/b",
                "abstract": "A null result was observed.",
                "license_name": "CC BY 4.0",
                "open_access_url": "https://example.edu/b.html",
            }
        ]

    def fetch(candidate: dict) -> FullTextArtifact:
        text = (
            "Anxiety declined after the intervention."
            if candidate["source_id"] == "paper-b"
            else "Anxiety was lower in the intervention group."
        )
        return FullTextArtifact(
            url=candidate["open_access_url"],
            mime_type="text/plain",
            content=text.encode(),
            license_name=candidate["license_name"],
        )

    with factory() as session:
        engine = DeepResearchEngine(
            session=session,
            provider=_Provider(),
            search=search,
            fetch_fulltext=fetch,
        )
        result = engine.run(
            run_id="run-1",
            project_id="project-1",
            seed_queries=["intervention anxiety"],
            subquestions=["Does the intervention reduce anxiety?"],
            limits=DeepResearchLimits(
                initial_rounds=1,
                max_rounds=4,
                initial_fulltexts=1,
                max_fulltexts=2,
                soft_timeout_minutes=5,
                hard_timeout_minutes=10,
            ),
        )

        documents = list(session.scalars(select(ResearchDocumentRecord)))
        claims = list(session.scalars(select(ResearchClaimRecord)))
        links = list(session.scalars(select(ClaimEvidenceLinkRecord)))
        subquestions = list(session.scalars(select(ResearchSubquestionRecord)))
        bindings = list(session.scalars(select(ResearchClaimSubquestionRecord)))

    assert result.iterations == 4
    assert result.fulltext_count == 2
    assert result.counter_evidence_coverage == 100
    assert result.stop_reason == "evidence_saturated"
    assert any("counter evidence" in query for query in calls[0])
    assert result.quality_gate_status == "PASS"
    assert result.quality_metrics["subquestion_coverage"] == 100
    assert result.quality_metrics["independent_source_coverage"] == 100
    assert result.quality_metrics["counter_search_coverage"] == 100
    assert result.quality_metrics["grounding_pass_rate"] == 100
    assert len(documents) == 2
    assert len(claims) == 1
    assert {link.stance for link in links} == {"supports", "counter"}
    assert [item.question for item in subquestions] == [
        "Does the intervention reduce anxiety?"
    ]
    assert len(bindings) == 1
    assert all(link.excerpt and link.validation_status == "validated" for link in links)


def test_deep_research_indexes_fulltext_and_reuses_global_memory(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'reuse.db').as_posix()}"
    )
    candidate = {
        "source": "arxiv",
        "source_id": "memory-paper",
        "title": "Reusable open evidence",
        "url": "https://example.edu/memory",
        "doi": "10.1/memory",
        "license_name": "CC BY 4.0",
        "open_access_url": "https://example.edu/memory.txt",
    }

    with factory() as session:
        memory = ResearchMemoryIndex(session, _Provider())
        first = DeepResearchEngine(
            session=session,
            provider=_Provider(),
            search=lambda _queries, _iteration: [candidate],
            fetch_fulltext=lambda _candidate: FullTextArtifact(
                url=candidate["open_access_url"],
                mime_type="text/plain",
                content=b"Students reported lower anxiety after the intervention.",
                license_name="CC BY 4.0",
            ),
            memory_index=memory,
        ).run(
            run_id="run-first",
            project_id="project-first",
            seed_queries=["student anxiety intervention"],
            subquestions=["Does the intervention reduce anxiety?"],
            limits=DeepResearchLimits(
                initial_rounds=1,
                max_rounds=1,
                initial_fulltexts=1,
                max_fulltexts=1,
                soft_timeout_minutes=5,
                hard_timeout_minutes=10,
            ),
        )
        second = DeepResearchEngine(
            session=session,
            provider=_Provider(),
            search=lambda _queries, _iteration: [],
            fetch_fulltext=lambda _candidate: None,
            memory_index=memory,
        ).run(
            run_id="run-second",
            project_id="project-second",
            seed_queries=["student anxiety intervention"],
            subquestions=["Does the intervention reduce anxiety?"],
            limits=DeepResearchLimits(
                initial_rounds=1,
                max_rounds=1,
                initial_fulltexts=1,
                max_fulltexts=1,
                soft_timeout_minutes=5,
                hard_timeout_minutes=10,
            ),
        )
        second_uses = list(
            session.scalars(
                select(ProjectEvidenceUseRecord).where(
                    ProjectEvidenceUseRecord.run_id == "run-second"
                )
            )
        )

    assert first.fulltext_count == 1
    assert second.fulltext_count == 0
    assert second.claim_count == 1
    assert len(second_uses) == 1


class _PromptCheckingProvider(_Provider):
    def complete_json(self, role, messages, schema=None):
        payload = json.loads(messages[-1]["content"])
        assert payload["subquestions"] == ["Primary question", "Boundary question"]
        return schema.model_validate(
            {
                "claims": [
                    {
                        "statement": "The effect only applies to novice learners.",
                        "stance": "qualifies",
                        "confidence": 90,
                        "excerpt": payload["chunk"],
                        "subquestion_index": 1,
                    }
                ]
            }
        ).model_dump(mode="json")


def test_extraction_prompt_binds_claims_to_the_selected_subquestion(tmp_path: Path) -> None:
    factory = build_session_factory(
        f"sqlite+pysqlite:///{(tmp_path / 'subquestions.db').as_posix()}"
    )
    with factory() as session:
        DeepResearchEngine(
            session=session,
            provider=_PromptCheckingProvider(),
            search=lambda _queries, _iteration: [
                {
                    "source": "arxiv",
                    "title": "Boundary evidence",
                    "url": "https://example.edu/boundary",
                    "doi": "10.1/boundary",
                    "license_name": "CC BY 4.0",
                }
            ],
            fetch_fulltext=lambda _candidate: FullTextArtifact(
                url="https://example.edu/boundary.txt",
                mime_type="text/plain",
                content=b"The effect only applies to novice learners.",
                license_name="CC BY 4.0",
            ),
        ).run(
            run_id="run-subquestions",
            project_id="project-subquestions",
            seed_queries=["learning effect"],
            subquestions=["Primary question", "Boundary question"],
            limits=DeepResearchLimits(
                initial_rounds=1,
                max_rounds=1,
                initial_fulltexts=1,
                max_fulltexts=1,
                soft_timeout_minutes=5,
                hard_timeout_minutes=10,
            ),
        )
        binding = session.scalar(select(ResearchClaimSubquestionRecord))
        selected = session.get(ResearchSubquestionRecord, binding.subquestion_id)

    assert selected.ordinal == 1
