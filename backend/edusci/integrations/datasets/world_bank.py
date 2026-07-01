from __future__ import annotations

import csv
from io import StringIO

from edusci.autonomy.contracts import DataRequirement, DatasetCandidateData, YearRange
from edusci.integrations.datasets.base import RetryingDatasetAdapter, token_overlap


class WorldBankAdapter(RetryingDatasetAdapter):
    name = "world_bank"
    allowed_hosts = frozenset({"api.worldbank.org"})
    base_url = "https://api.worldbank.org/v2"

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]:
        payload = self._get_json(
            f"{self.base_url}/indicator",
            {"format": "json", "per_page": 20000},
        )
        items = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        ranked = sorted(
            items,
            key=lambda item: token_overlap(
                requirement.concept,
                f"{item.get('name', '')} {item.get('sourceNote', '')}",
            ),
            reverse=True,
        )
        results: list[DatasetCandidateData] = []
        for item in ranked:
            relevance = token_overlap(
                requirement.concept,
                f"{item.get('name', '')} {item.get('sourceNote', '')}",
            )
            if relevance == 0:
                continue
            indicator_id = str(item.get("id") or "")
            if not indicator_id:
                continue
            results.append(
                DatasetCandidateData(
                    source=self.name,
                    dataset_id=indicator_id,
                    title=item.get("name") or indicator_id,
                    description=item.get("sourceNote") or "",
                    provenance_url=f"{self.base_url}/indicator/{indicator_id}",
                    download_url=f"{self.base_url}/country/CHN/indicator/{indicator_id}",
                    geographies=["all"],
                    unit=item.get("unit") or requirement.unit_hint,
                    frequency="annual",
                    license_name="World Bank Data License",
                    license_url="https://datacatalog.worldbank.org/public-licenses",
                    license_status="allowed",
                    fields=["country", "year", "value", "indicator_id"],
                    variable_mapping={requirement.concept: "value"},
                    variable_coverage=100,
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
        countries = ";".join(geography or ["all"])
        payload = self._get_json(
            f"{self.base_url}/country/{countries}/indicator/{candidate.dataset_id}",
            {
                "format": "json",
                "date": f"{years.start}:{years.end}",
                "per_page": 20000,
            },
        )
        observations = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        buffer = StringIO()
        writer = csv.DictWriter(
            buffer, fieldnames=["country", "year", "value", "indicator_id"]
        )
        writer.writeheader()
        for item in observations or []:
            writer.writerow(
                {
                    "country": item.get("countryiso3code") or "",
                    "year": item.get("date") or "",
                    "value": item.get("value"),
                    "indicator_id": (item.get("indicator") or {}).get("id")
                    or candidate.dataset_id,
                }
            )
        return buffer.getvalue().encode("utf-8-sig")

