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
    ResearchClaimRecord,
    ResearchDocumentRecord,
)


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

    def complete_json(self, role, messages, schema=None):
        text = messages[-1]["content"]
        if "declined" in text:
            payload = {
                "claims": [
                    {
                        "statement": "The intervention reduced anxiety.",
                        "stance": "counter",
                        "confidence": 86,
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
                max_rounds=2,
                initial_fulltexts=1,
                max_fulltexts=2,
                soft_timeout_minutes=5,
                hard_timeout_minutes=10,
            ),
        )

        documents = list(session.scalars(select(ResearchDocumentRecord)))
        claims = list(session.scalars(select(ResearchClaimRecord)))
        links = list(session.scalars(select(ClaimEvidenceLinkRecord)))

    assert result.iterations == 2
    assert result.fulltext_count == 2
    assert result.counter_evidence_coverage == 100
    assert result.stop_reason == "evidence_saturated"
    assert any("counter evidence" in query for query in calls[1])
    assert len(documents) == 2
    assert len(claims) == 1
    assert {link.stance for link in links} == {"supports", "counter"}
