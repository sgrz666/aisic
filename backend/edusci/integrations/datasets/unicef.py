from __future__ import annotations

from edusci.autonomy.contracts import DataRequirement, DatasetCandidateData, YearRange
from edusci.integrations.datasets.base import RetryingDatasetAdapter, token_overlap


class UnicefSdmxAdapter(RetryingDatasetAdapter):
    name = "unicef"
    allowed_hosts = frozenset({"sdmx.data.unicef.org"})
    base_url = "https://sdmx.data.unicef.org/ws/public/sdmxapi/rest"

    @staticmethod
    def _flows(payload) -> list[dict]:
        if isinstance(payload, dict):
            if isinstance(payload.get("dataflows"), list):
                return payload["dataflows"]
            for value in payload.values():
                flows = UnicefSdmxAdapter._flows(value)
                if flows:
                    return flows
        if isinstance(payload, list):
            if payload and all(isinstance(item, dict) and "id" in item for item in payload):
                return payload
            for value in payload:
                flows = UnicefSdmxAdapter._flows(value)
                if flows:
                    return flows
        return []

    def search(
        self, requirement: DataRequirement, limit: int
    ) -> list[DatasetCandidateData]:
        payload = self._get_json(
            f"{self.base_url}/dataflow/all/all/latest/",
            {"format": "sdmx-json", "detail": "full", "references": "none"},
        )
        ranked = sorted(
            self._flows(payload),
            key=lambda item: token_overlap(
                requirement.concept,
                f"{item.get('id', '')} {item.get('name', '')}",
            ),
            reverse=True,
        )
        results: list[DatasetCandidateData] = []
        for flow in ranked:
            agency = str(flow.get("agencyID") or flow.get("agencyId") or "")
            if agency.upper() != "UNICEF":
                continue
            flow_id = str(flow.get("id") or "")
            name = flow.get("name") or flow_id
            if token_overlap(requirement.concept, f"{flow_id} {name}") == 0:
                continue
            results.append(
                DatasetCandidateData(
                    source=self.name,
                    dataset_id=flow_id,
                    title=str(name),
                    provenance_url=f"{self.base_url}/dataflow/UNICEF/{flow_id}/latest/",
                    download_url=f"{self.base_url}/data/UNICEF,{flow_id},1.0/all",
                    geographies=["all"],
                    unit=requirement.unit_hint,
                    frequency="annual",
                    license_name="UNICEF Data Terms",
                    license_url="https://data.unicef.org/legal/",
                    license_status="allowed",
                    fields=["reference_area", "indicator", "year", "value"],
                    variable_mapping={requirement.concept: "value"},
                    variable_coverage=80,
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
        query = "+".join(geography) if geography else "all"
        url = f"{self.base_url}/data/UNICEF,{candidate.dataset_id},1.0/{query}"
        response = self._request(
            url,
            {
                "format": "csvfile",
                "startPeriod": years.start,
                "endPeriod": years.end,
            },
        )
        return response.content

