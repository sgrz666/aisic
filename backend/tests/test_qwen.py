import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from edusci.app import create_app
from edusci.integrations.qwen import QwenConfigurationError, QwenProvider


def test_qwen_provider_uses_review_model_and_openai_compatible_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"verdict":"PASS"}'}}]},
        )

    provider = QwenProvider(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        generation_model="qwen-plus",
        review_model="qwen-max",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.complete_json("review", [{"role": "user", "content": "审查"}])

    payload = json.loads(requests[0].content)
    assert requests[0].url.path.endswith("/compatible-mode/v1/chat/completions")
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert payload["model"] == "qwen-max"
    assert result == {"verdict": "PASS"}


def test_qwen_structured_output_repairs_once_after_invalid_json() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = "不是 JSON" if attempts == 1 else '{"problem":"已修复"}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = QwenProvider(
        api_key="test-key",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert provider.complete_json("generation", [{"role": "user", "content": "解析"}]) == {
        "problem": "已修复"
    }
    assert attempts == 2


def test_qwen_provider_requires_api_key() -> None:
    with pytest.raises(QwenConfigurationError, match="DASHSCOPE_API_KEY"):
        QwenProvider(api_key="")


def test_qwen_roles_and_usage_are_tracked() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok":true}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    provider = QwenProvider(
        api_key="test-key",
        generation_model="qwen3.7-plus",
        review_model="qwen3.7-max",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    provider.complete_json("extractor", [{"role": "user", "content": "extract"}])
    provider.complete_json("synthesis", [{"role": "user", "content": "synthesize"}])

    assert json.loads(requests[0].content)["model"] == "qwen3.7-plus"
    assert json.loads(requests[1].content)["model"] == "qwen3.7-max"
    assert provider.usage == {
        "requests": 2,
        "prompt_tokens": 24,
        "completion_tokens": 8,
        "total_tokens": 32,
    }


def test_qwen_retries_transient_api_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"message": "rate limited"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    provider = QwenProvider(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_backoff_seconds=0,
    )

    assert provider.complete("planner", [{"role": "user", "content": "plan"}]) == "ok"
    assert attempts == 2


class _StructuredAnswer(BaseModel):
    coverage: int = Field(ge=0, le=100)


def test_qwen_repairs_json_that_fails_the_requested_schema() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        content = '{"coverage":140}' if attempts == 1 else '{"coverage":88}'
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    provider = QwenProvider(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.complete_json(
        "extractor",
        [{"role": "user", "content": "score"}],
        schema=_StructuredAnswer,
    )

    assert result == {"coverage": 88}
    assert attempts == 2


def test_qwen_embeddings_use_configured_model_dimension_and_track_usage() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                ],
                "usage": {"total_tokens": 7},
            },
        )

    provider = QwenProvider(
        api_key="test-key",
        embedding_model="text-embedding-v4",
        embedding_dimension=3,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    vectors = provider.embed(["研究问题", "research question"])

    payload = json.loads(requests[0].content)
    assert requests[0].url.path.endswith("/compatible-mode/v1/embeddings")
    assert payload == {
        "model": "text-embedding-v4",
        "input": ["研究问题", "research question"],
        "dimensions": 3,
    }
    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert provider.usage["requests"] == 1
    assert provider.usage["total_tokens"] == 7


def test_qwen_embeddings_reject_an_invalid_vector_dimension() -> None:
    provider = QwenProvider(
        api_key="test-key",
        embedding_dimension=3,
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]},
                )
            )
        ),
    )

    with pytest.raises(ValueError, match="向量维度"):
        provider.embed(["dimension mismatch"])


def test_app_reads_qwen_embedding_configuration(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    monkeypatch.setenv("QWEN_EMBEDDING_MODEL", "text-embedding-test")
    monkeypatch.setenv("QWEN_EMBEDDING_DIMENSION", "768")

    app = create_app(
        database_url=f"sqlite+pysqlite:///{(tmp_path / 'app.db').as_posix()}",
        literature_adapters=[],
        dataset_adapters=[],
    )

    with TestClient(app):
        provider = app.state.model_provider
        assert provider.embedding_model == "text-embedding-test"
        assert provider.embedding_dimension == 768


def test_qwen_evidence_verifier_uses_a_strict_schema() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "status": "validated",
                                    "stance": "supports",
                                    "entailment_score": 91,
                                    "reason": "The excerpt directly states the claim.",
                                }
                            )
                        }
                    }
                ]
            },
        )

    provider = QwenProvider(
        api_key="test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    result = provider.verify_evidence(
        statement="The intervention reduced anxiety.",
        excerpt="Students reported lower anxiety after the intervention.",
        stance="supports",
    )

    payload = json.loads(requests[0].content)
    assert payload["model"] == "qwen3.7-plus"
    assert payload["response_format"] == {"type": "json_object"}
    assert result == {
        "status": "validated",
        "stance": "supports",
        "entailment_score": 91,
        "reason": "The excerpt directly states the claim.",
    }
