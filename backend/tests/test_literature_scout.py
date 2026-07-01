from edusci.autonomy.contracts import LiteratureQuery
from edusci.autonomy.literature import LiteratureScout
from tests.autonomy_fakes import FakeLiteratureAdapter


def test_scout_deduplicates_doi_and_records_attempts() -> None:
    adapter = FakeLiteratureAdapter(
        [
            {
                "source_id": "p1",
                "title": "School population and resources",
                "doi": "10.1/a",
                "abstract": "School-age population predicts education resource demand across regions.",
                "year": 2024,
                "url": "https://doi.org/10.1/a",
                "citation_count": 20,
            },
            {
                "source_id": "p2",
                "title": "School population and resources",
                "doi": "10.1/A",
                "abstract": "Duplicate record with the same DOI and fewer metadata fields.",
                "year": 2024,
                "url": "https://doi.org/10.1/a",
                "citation_count": 20,
            },
        ]
    )
    scout = LiteratureScout([adapter], max_rounds=3)

    result = scout.discover(
        [
            LiteratureQuery(
                query="school population resources", language="en", purpose="broad"
            )
        ],
        concepts=["population", "resources"],
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].doi == "10.1/a"
    assert result.candidates[0].relevance_score >= 70
    assert result.attempts[0].source == "fake_literature"


def test_scout_degrades_when_one_source_fails() -> None:
    failed = FakeLiteratureAdapter([], fail=True)
    failed.name = "failed_source"
    healthy = FakeLiteratureAdapter(
        [
            {
                "source_id": "healthy-1",
                "title": "Population and education resources",
                "doi": "10.1/healthy",
                "abstract": "Population change is associated with education resource allocation demand.",
                "year": 2025,
                "url": "https://doi.org/10.1/healthy",
                "citation_count": 4,
            }
        ]
    )
    healthy.name = "healthy_source"

    result = LiteratureScout([failed, healthy], max_rounds=1).discover(
        [
            LiteratureQuery(
                query="population education resources", language="en", purpose="broad"
            )
        ],
        concepts=["population", "education resources"],
    )

    assert len(result.candidates) == 1
    assert any(attempt.source == "failed_source" and attempt.error for attempt in result.attempts)
    assert any(attempt.source == "healthy_source" and not attempt.error for attempt in result.attempts)


def test_scout_excludes_title_only_results_from_pass_evidence() -> None:
    adapter = FakeLiteratureAdapter(
        [
            {
                "source_id": "title-only",
                "title": "Education resources",
                "doi": "10.1/title",
                "abstract": "",
                "year": 2024,
                "url": "https://doi.org/10.1/title",
            }
        ]
    )

    result = LiteratureScout([adapter], max_rounds=1).discover(
        [LiteratureQuery(query="education resources", language="en", purpose="broad")],
        concepts=["education", "resources"],
    )

    assert result.candidates[0].exclusion_reason == "abstract_too_short"
