import httpx

from edusci.autonomy.contracts import DataRequirement, YearRange
from edusci.integrations.datasets.moe import MoeStatisticsAdapter
from edusci.integrations.datasets.unesco import UnescoUisAdapter
from edusci.integrations.datasets.unicef import UnicefSdmxAdapter
from edusci.integrations.datasets.world_bank import WorldBankAdapter


REQUIREMENT = DataRequirement(
    concept="school-age population",
    unit_hint="people",
    required=True,
)


def client_with(routes: dict[str, object]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        for fragment, payload in routes.items():
            if fragment in str(request.url):
                if isinstance(payload, str):
                    return httpx.Response(200, text=payload, request=request)
                return httpx.Response(200, json=payload, request=request)
        return httpx.Response(404, request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def assert_candidate(candidate, source: str) -> None:
    assert candidate.source == source
    assert candidate.dataset_id
    assert candidate.title
    assert candidate.provenance_url.startswith("https://")
    assert candidate.license_status in {"allowed", "review"}


def test_world_bank_search_maps_indicator_and_downloads_tabular_csv() -> None:
    client = client_with(
        {
            "/indicator?": [
                {"page": 1, "pages": 1},
                [
                    {
                        "id": "SP.POP.0014.TO",
                        "name": "Population ages 0-14, total",
                        "sourceNote": "Population of children ages 0 to 14.",
                        "unit": "people",
                    }
                ],
            ],
            "/country/CHN/indicator/": [
                {"page": 1},
                [
                    {
                        "countryiso3code": "CHN",
                        "date": "2024",
                        "value": 200,
                        "indicator": {"id": "SP.POP.0014.TO", "value": "Population"},
                    }
                ],
            ],
        }
    )
    adapter = WorldBankAdapter(client)
    candidate = adapter.search(REQUIREMENT, limit=5)[0]

    assert_candidate(candidate, "world_bank")
    assert candidate.unit == "people"
    downloaded = adapter.download(candidate, ["CHN"], years=YearRange(start=2020, end=2026))
    assert b"country,year,value" in downloaded
    assert b"CHN,2024,200" in downloaded


def test_unicef_search_maps_official_sdmx_flow() -> None:
    payload = {
        "structure": {
            "dataflows": [
                {
                    "id": "EDUCATION_UIS_SDG",
                    "agencyID": "UNICEF",
                    "name": "Education UIS SDG school age population",
                }
            ]
        }
    }
    candidate = UnicefSdmxAdapter(client_with({"dataflow": payload})).search(
        REQUIREMENT, 5
    )[0]

    assert_candidate(candidate, "unicef")
    assert candidate.frequency == "annual"


def test_unesco_search_maps_indicator_definition() -> None:
    payload = [
        {
            "id": "X_SCHOOL_AGE_POP",
            "name": "School age population",
            "description": "Population at the official age for primary education",
            "unit": "people",
        }
    ]
    candidate = UnescoUisAdapter(
        client_with({"definitions/indicators": payload})
    ).search(REQUIREMENT, 5)[0]

    assert_candidate(candidate, "unesco_uis")
    assert candidate.license_name == "CC BY-SA 4.0"


def test_moe_search_keeps_page_provenance_for_review() -> None:
    html = """
    <html><head><title>2024年教育统计数据</title></head><body>
      <a href="/jyb_sjzl/moe_560/2024/gedi.html">各地学校数和在校生数</a>
    </body></html>
    """
    candidate = MoeStatisticsAdapter(client_with({"moe_560": html})).search(
        DataRequirement(concept="学校数", unit_hint="count"), 5
    )[0]

    assert_candidate(candidate, "moe")
    assert candidate.license_status == "review"
    assert candidate.provenance_url.endswith("gedi.html")


def test_dataset_adapter_rejects_non_whitelisted_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "https://evil.example/data.csv"},
            request=request,
        )

    adapter = WorldBankAdapter(
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
    )

    try:
        adapter.search(REQUIREMENT, 1)
    except RuntimeError as exc:
        assert "白名单" in str(exc) or "失败" in str(exc)
    else:
        raise AssertionError("非白名单重定向必须失败")
