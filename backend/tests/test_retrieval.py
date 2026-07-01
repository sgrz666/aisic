import httpx

from edusci.integrations.retrieval import OpenResearchRetriever


def test_open_retriever_normalizes_crossref_and_semantic_scholar() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "items": [
                            {
                                "title": ["AI anxiety among university students"],
                                "DOI": "10.1000/ai-anxiety",
                                "abstract": "<jats:p>AI anxiety differs across student groups.</jats:p>",
                                "type": "journal-article",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "title": "Artificial intelligence anxiety in education",
                        "url": "https://www.semanticscholar.org/paper/abc",
                        "abstract": "A validated study of AI anxiety in higher education.",
                        "year": 2025,
                    }
                ]
            },
        )

    retriever = OpenResearchRetriever(client=httpx.Client(transport=httpx.MockTransport(handler)))
    sources = retriever.search("大学生 AI 焦虑", limit=4)

    assert len(sources) == 2
    assert sources[0].url.startswith("https://doi.org/")
    assert "<jats" not in sources[0].excerpt
    assert sources[1].locator == "Semantic Scholar 摘要（2025）"

