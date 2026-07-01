from __future__ import annotations

import hashlib
from io import StringIO
from urllib.parse import urljoin

import pandas as pd
from bs4 import BeautifulSoup

from edusci.autonomy.contracts import DataRequirement, DatasetCandidateData, YearRange
from edusci.integrations.datasets.base import RetryingDatasetAdapter


class MoeStatisticsAdapter(RetryingDatasetAdapter):
    name = "moe"
    allowed_hosts = frozenset({"www.moe.gov.cn"})
    index_url = "https://www.moe.gov.cn/jyb_sjzl/moe_560/"

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]:
        html = self._get_text(self.index_url)
        soup = BeautifulSoup(html, "lxml")
        terms = [term for term in requirement.concept.replace("、", " ").split() if term]
        results: list[DatasetCandidateData] = []
        for link in soup.find_all("a", href=True):
            title = " ".join(link.get_text(" ", strip=True).split())
            if not title or not any(term in title for term in terms):
                continue
            url = urljoin(self.index_url, link["href"])
            if not url.startswith("https://www.moe.gov.cn/"):
                continue
            results.append(
                DatasetCandidateData(
                    source=self.name,
                    dataset_id=hashlib.sha256(url.encode("utf-8")).hexdigest()[:24],
                    title=title,
                    provenance_url=url,
                    download_url=url,
                    geographies=["CHN"],
                    unit=requirement.unit_hint,
                    frequency="annual",
                    license_name="教育部政府信息公开",
                    license_url="https://www.moe.gov.cn/jyb_xxgk/",
                    license_status="review",
                    fields=[],
                    variable_mapping={},
                    variable_coverage=0,
                )
            )
            if len(results) >= limit:
                break
        return results

    def download(
        self,
        candidate: DatasetCandidateData,
        geography: list[str],
        years: YearRange,
    ) -> bytes:
        html = self._get_text(candidate.download_url)
        tables = pd.read_html(StringIO(html))
        if not tables:
            raise RuntimeError("教育部页面未发现结构化表格")
        return tables[0].to_csv(index=False).encode("utf-8-sig")

