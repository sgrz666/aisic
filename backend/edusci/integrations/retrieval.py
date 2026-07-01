from __future__ import annotations

import os
import re
import time

import httpx

from edusci.api.schemas import SourceInput


class _LiteratureHttpAdapter:
    name = "literature"

    def __init__(self, client: httpx.Client | None = None, max_retries: int = 3) -> None:
        self.client = client or httpx.Client(
            timeout=20, headers={"User-Agent": "EduSci-MVP/0.2"}
        )
        self.max_retries = max_retries

    def _get_json(self, url: str, params: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.get(url, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(0.05 * (2**attempt))
        raise RuntimeError(f"{self.name} 连续失败 {self.max_retries} 次: {last_error}")

    @staticmethod
    def _clean(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"<[^>]+>", "", value).strip()


class CrossrefLiteratureAdapter(_LiteratureHttpAdapter):
    name = "crossref"

    def search(self, query: str, limit: int) -> list[dict]:
        data = self._get_json(
            "https://api.crossref.org/works",
            {
                "query.bibliographic": query,
                "rows": limit,
                "select": "title,DOI,abstract,type,author,published,license,URL,container-title,volume,issue,page,publisher",
            },
        )
        results: list[dict] = []
        for item in data.get("message", {}).get("items", []):
            titles = item.get("title") or []
            doi = str(item.get("DOI") or "").lower()
            published = item.get("published", {}).get("date-parts", [[None]])
            year = published[0][0] if published and published[0] else None
            authors = [
                " ".join(filter(None, (author.get("given"), author.get("family"))))
                for author in item.get("author", [])
            ]
            licenses = item.get("license") or []
            results.append(
                {
                    "source_id": doi or str(item.get("URL") or ""),
                    "title": titles[0] if titles else "未命名文献",
                    "doi": doi,
                    "abstract": self._clean(item.get("abstract")),
                    "authors": authors,
                    "year": year,
                    "url": item.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
                    "license_url": licenses[0].get("URL", "") if licenses else "",
                    "citation_count": 0,
                    "source_title": (item.get("container-title") or [""])[0],
                    "volume": item.get("volume") or "",
                    "issue": item.get("issue") or "",
                    "pages": item.get("page") or "",
                    "publisher": item.get("publisher") or "",
                    "reference_type": "J",
                }
            )
        return results

    def related(self, source_id: str, limit: int) -> list[dict]:
        return []


class SemanticScholarLiteratureAdapter(_LiteratureHttpAdapter):
    name = "semantic_scholar"

    _fields = (
        "paperId,title,url,abstract,year,authors,externalIds,citationCount,"
        "fieldsOfStudy,publicationDate,venue,journal"
    )

    def __init__(
        self,
        client: httpx.Client | None = None,
        max_retries: int = 3,
        api_key: str | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("SEMANTIC_SCHOLAR_API_KEY", "").strip()
        if client is None and resolved_key:
            client = httpx.Client(
                timeout=20,
                headers={"User-Agent": "EduSci-MVP/0.2", "x-api-key": resolved_key},
            )
        super().__init__(client, max_retries)

    def search(self, query: str, limit: int) -> list[dict]:
        data = self._get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query, "limit": limit, "fields": self._fields},
        )
        return [self._normalize(item) for item in data.get("data", [])]

    def related(self, source_id: str, limit: int) -> list[dict]:
        if not source_id:
            return []
        data = self._get_json(
            f"https://api.semanticscholar.org/recommendations/v1/papers/forpaper/{source_id}",
            {"limit": limit, "fields": self._fields},
        )
        return [self._normalize(item) for item in data.get("recommendedPapers", [])]

    def _normalize(self, item: dict) -> dict:
        external = item.get("externalIds") or {}
        doi = str(external.get("DOI") or "").lower()
        return {
            "source_id": str(item.get("paperId") or doi or item.get("url") or ""),
            "title": item.get("title") or "未命名文献",
            "doi": doi,
            "abstract": self._clean(item.get("abstract")),
            "authors": [author.get("name", "") for author in item.get("authors") or []],
            "year": item.get("year"),
            "url": item.get("url") or (f"https://doi.org/{doi}" if doi else ""),
            "license_url": "",
            "citation_count": int(item.get("citationCount") or 0),
            "source_title": (item.get("journal") or {}).get("name") or item.get("venue") or "",
            "volume": (item.get("journal") or {}).get("volume") or "",
            "pages": (item.get("journal") or {}).get("pages") or "",
            "reference_type": "J",
        }


class OpenResearchRetriever:
    """Compatibility facade used by the existing evidence endpoint."""

    def __init__(self, client: httpx.Client | None = None, max_retries: int = 3) -> None:
        self.adapters = [
            CrossrefLiteratureAdapter(client, max_retries),
            SemanticScholarLiteratureAdapter(client, max_retries),
        ]

    def search(self, query: str, limit: int = 6) -> list[SourceInput]:
        per_source = max(1, limit // 2)
        raw: list[tuple[str, dict]] = []
        for adapter in self.adapters:
            try:
                raw.extend((adapter.name, item) for item in adapter.search(query, per_source))
            except RuntimeError:
                continue
        sources: list[SourceInput] = []
        seen: set[str] = set()
        for source_name, item in raw:
            key = (item.get("doi") or item.get("url") or item.get("title", "")).lower()
            if key in seen:
                continue
            seen.add(key)
            year = item.get("year") or "年份未知"
            locator = "Crossref 摘要" if source_name == "crossref" else f"Semantic Scholar 摘要（{year}）"
            sources.append(
                SourceInput(
                    title=item["title"],
                    source_type="journal",
                    url=item.get("url") or "",
                    locator=locator,
                    excerpt=item.get("abstract") or item["title"],
                    verified=True,
                )
            )
        return sources[:limit]
