from __future__ import annotations

import time
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from edusci.autonomy.contracts import DataRequirement, DatasetCandidateData, YearRange


class DatasetSourceAdapter(Protocol):
    name: str

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]: ...

    def download(
        self,
        candidate: DatasetCandidateData,
        geography: list[str],
        years: YearRange,
    ) -> bytes: ...


class RetryingDatasetAdapter:
    name = "dataset"
    allowed_hosts: frozenset[str] = frozenset()
    max_size_bytes = 50 * 1024 * 1024

    def __init__(self, client: httpx.Client | None = None, max_retries: int = 3) -> None:
        self.client = client or httpx.Client(
            timeout=30,
            follow_redirects=True,
            headers={"User-Agent": "EduSci-MVP/0.2"},
        )
        self.max_retries = max(1, max_retries)

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.allowed_hosts:
            raise RuntimeError(f"{self.name} 拒绝非 HTTPS 或非白名单地址: {url}")

    def _request(self, url: str, params: dict | None = None) -> httpx.Response:
        self._validate_url(url)
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = self.client.get(url, params=params)
                for previous in response.history:
                    location = previous.headers.get("location")
                    if location:
                        self._validate_url(urljoin(str(previous.url), location))
                self._validate_url(str(response.url))
                if 300 <= response.status_code < 400 and response.headers.get("location"):
                    self._validate_url(urljoin(str(response.url), response.headers["location"]))
                response.raise_for_status()
                content_length = int(response.headers.get("content-length") or len(response.content))
                if content_length > self.max_size_bytes or len(response.content) > self.max_size_bytes:
                    raise RuntimeError(f"{self.name} 响应超过 50 MB")
                return response
            except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(0.05 * (2**attempt))
        raise RuntimeError(f"{self.name} 连续失败 {self.max_retries} 次: {last_error}")

    def _get_json(self, url: str, params: dict | None = None):
        try:
            return self._request(url, params).json()
        except ValueError as exc:
            raise RuntimeError(f"{self.name} 返回了无效 JSON") from exc

    def _get_text(self, url: str, params: dict | None = None) -> str:
        return self._request(url, params).text


def token_overlap(query: str, text: str) -> int:
    tokens = {
        token.lower()
        for token in query.replace("-", " ").replace("_", " ").split()
        if len(token) >= 3
    }
    haystack = text.lower()
    return sum(token in haystack for token in tokens)

