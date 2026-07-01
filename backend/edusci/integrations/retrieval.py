from __future__ import annotations

import re
import time

import httpx

from edusci.api.schemas import SourceInput


class OpenResearchRetriever:
    def __init__(self, client: httpx.Client | None = None, max_retries: int = 3) -> None:
        self.client = client or httpx.Client(timeout=20, headers={"User-Agent": "EduSci-MVP/0.1"})
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
        raise RuntimeError(f"开放检索连续失败 {self.max_retries} 次: {last_error}")

    @staticmethod
    def _clean(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"<[^>]+>", "", value).strip()

    def _crossref(self, query: str, limit: int) -> list[SourceInput]:
        data = self._get_json(
            "https://api.crossref.org/works",
            {"query.bibliographic": query, "rows": limit, "select": "title,DOI,abstract,type"},
        )
        sources: list[SourceInput] = []
        for item in data.get("message", {}).get("items", []):
            title_values = item.get("title") or []
            title = title_values[0] if title_values else "未命名文献"
            doi = item.get("DOI", "")
            excerpt = self._clean(item.get("abstract")) or title
            sources.append(
                SourceInput(
                    title=title,
                    source_type="journal",
                    url=f"https://doi.org/{doi}" if doi else "",
                    locator="Crossref 摘要",
                    excerpt=excerpt,
                    verified=True,
                )
            )
        return sources

    def _semantic_scholar(self, query: str, limit: int) -> list[SourceInput]:
        data = self._get_json(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            {"query": query, "limit": limit, "fields": "title,url,abstract,year"},
        )
        return [
            SourceInput(
                title=item.get("title") or "未命名文献",
                source_type="journal",
                url=item.get("url") or "",
                locator=f"Semantic Scholar 摘要（{item.get('year') or '年份未知'}）",
                excerpt=self._clean(item.get("abstract")) or item.get("title") or "",
                verified=True,
            )
            for item in data.get("data", [])
        ]

    def search(self, query: str, limit: int = 6) -> list[SourceInput]:
        per_source = max(1, limit // 2)
        sources: list[SourceInput] = []
        for adapter in (self._crossref, self._semantic_scholar):
            try:
                sources.extend(adapter(query, per_source))
            except RuntimeError:
                continue
        deduplicated: list[SourceInput] = []
        seen: set[str] = set()
        for source in sources:
            key = (source.url or source.title).lower()
            if key in seen:
                continue
            seen.add(key)
            deduplicated.append(source)
        return deduplicated[:limit]
