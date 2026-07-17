import httpx

from edusci.integrations.retrieval import (
    OpenAccessFullTextFetcher,
    SemanticScholarLiteratureAdapter,
)


def test_semantic_scholar_exposes_open_access_pdf() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "paperId": "p1",
                        "title": "Open paper",
                        "url": "https://www.semanticscholar.org/paper/p1",
                        "abstract": "A sufficiently detailed abstract for testing.",
                        "openAccessPdf": {
                            "url": "https://arxiv.org/pdf/2501.00001",
                            "status": "GREEN",
                            "license": "CC BY 4.0",
                        },
                    }
                ]
            },
        )

    adapter = SemanticScholarLiteratureAdapter(
        httpx.Client(transport=httpx.MockTransport(handler))
    )

    result = adapter.search("open", 1)[0]

    assert result["open_access_url"] == "https://arxiv.org/pdf/2501.00001"
    assert result["license_name"] == "CC BY 4.0"


def test_fulltext_fetcher_rejects_unlicensed_arbitrary_webpage() -> None:
    fetcher = OpenAccessFullTextFetcher(
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text="x")))
    )

    assert fetcher.fetch(
        {
            "url": "https://commercial.example/article",
            "open_access_url": "https://commercial.example/article",
            "license_name": "",
        }
    ) is None


def test_fulltext_fetcher_accepts_licensed_pdf_and_enforces_size_limit() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"%PDF-small",
            headers={"content-type": "application/pdf"},
        )

    fetcher = OpenAccessFullTextFetcher(
        httpx.Client(transport=httpx.MockTransport(handler)), max_size_bytes=100
    )

    artifact = fetcher.fetch(
        {
            "open_access_url": "https://arxiv.org/pdf/2501.00001",
            "license_name": "CC BY 4.0",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
        }
    )

    assert artifact is not None
    assert artifact.mime_type == "application/pdf"
    assert artifact.content == b"%PDF-small"
