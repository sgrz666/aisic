import json

import httpx
import pytest

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

