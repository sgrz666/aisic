from __future__ import annotations

import csv
from io import StringIO

from edusci.autonomy.contracts import DataRequirement, DatasetCandidateData, YearRange
from edusci.integrations.datasets.base import RetryingDatasetAdapter, token_overlap


class UnescoUisAdapter(RetryingDatasetAdapter):
    name = "unesco_uis"
    allowed_hosts = frozenset({"api.uis.unesco.org"})
    base_url = "https://api.uis.unesco.org/api/public"

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]:
        payload = self._get_json(f"{self.base_url}/definitions/indicators")
        items = payload.get("data", payload.get("results", [])) if isinstance(payload, dict) else payload
        ranked = sorted(
            items or [],
            key=lambda item: token_overlap(
                requirement.concept,
                f"{item.get('id', '')} {item.get('name', '')} {item.get('description', '')}",
            ),
            reverse=True,
        )
        results: list[DatasetCandidateData] = []
        for item in ranked:
            text = f"{item.get('id', '')} {item.get('name', '')} {item.get('description', '')}"
            if token_overlap(requirement.concept, text) == 0:
                continue
            indicator_id = str(item.get("id") or item.get("indicatorId") or "")
            if not indicator_id:
                continue
            results.append(
                DatasetCandidateData(
                    source=self.name,
                    dataset_id=indicator_id,
                    title=item.get("name") or indicator_id,
                    description=item.get("description") or "",
                    provenance_url=f"{self.base_url}/definitions/indicators",
                    download_url=f"{self.base_url}/data/indicators?indicator={indicator_id}",
                    geographies=["all"],
                    unit=item.get("unit") or requirement.unit_hint,
                    frequency="annual",
                    license_name="CC BY-SA 4.0",
                    license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                    license_status="allowed",
                    fields=["indicator", "geo_unit", "year", "value"],
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
        params: dict = {
            "indicator": candidate.dataset_id,
            "start": years.start,
            "end": years.end,
            "indicatorMetadata": "true",
            "footnotes": "true",
        }
        if geography:
            params["geoUnit"] = ",".join(geography)
        payload = self._get_json(f"{self.base_url}/data/indicators", params)
        items = payload.get("data", payload.get("results", [])) if isinstance(payload, dict) else payload
        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=["indicator", "geo_unit", "year", "value"])
        writer.writeheader()
        for item in items or []:
            writer.writerow(
                {
                    "indicator": item.get("indicator") or item.get("indicatorId") or candidate.dataset_id,
                    "geo_unit": item.get("geoUnit") or item.get("geo_unit") or "",
                    "year": item.get("year") or "",
                    "value": item.get("value"),
                }
            )
        return buffer.getvalue().encode("utf-8-sig")

