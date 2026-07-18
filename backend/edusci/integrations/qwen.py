from __future__ import annotations

import json
import re
import time
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

ModelRole = Literal[
    "generation", "review", "planner", "extractor", "synthesis"
]


class QwenConfigurationError(ValueError):
    pass


class QwenStructuredOutputError(ValueError):
    pass


class EvidenceVerification(BaseModel):
    status: Literal["validated", "rejected"]
    stance: Literal["supports", "counter", "qualifies"]
    entailment_score: int
    reason: str


class QwenProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        generation_model: str = "qwen3.7-plus",
        review_model: str = "qwen3.7-max",
        embedding_model: str = "text-embedding-v4",
        embedding_dimension: int = 1024,
        client: httpx.Client | None = None,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        if not api_key.strip():
            raise QwenConfigurationError("请配置 DASHSCOPE_API_KEY")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model
        self.review_model = review_model
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.client = client or httpx.Client(timeout=90)
        self.retry_backoff_seconds = retry_backoff_seconds
        self.usage = {
            "requests": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.request_ids: list[str] = []

    def _model(self, role: ModelRole) -> str:
        return self.review_model if role in {"review", "synthesis"} else self.generation_model

    def complete(self, role: ModelRole, messages: list[dict], json_mode: bool = False) -> str:
        payload: dict = {"model": self._model(role), "messages": messages, "temperature": 0.2}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if response.status_code not in {408, 429} and response.status_code < 500:
                    response.raise_for_status()
                    break
            except httpx.TransportError:
                if attempt == 2:
                    raise
            if attempt == 2:
                assert response is not None
                response.raise_for_status()
            time.sleep(self.retry_backoff_seconds * (2**attempt))

        assert response is not None
        data = response.json()
        usage = data.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += prompt_tokens
        self.usage["completion_tokens"] += completion_tokens
        self.usage["total_tokens"] += prompt_tokens + completion_tokens
        request_id = response.headers.get("x-request-id") or data.get("request_id")
        if request_id:
            self.request_ids.append(str(request_id))
        return str(data["choices"][0]["message"]["content"])

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = {
            "model": self.embedding_model,
            "input": texts,
            "dimensions": self.embedding_dimension,
        }
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = self.client.post(
                    f"{self.base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                if response.status_code not in {408, 429} and response.status_code < 500:
                    response.raise_for_status()
                    break
            except httpx.TransportError:
                if attempt == 2:
                    raise
            if attempt == 2:
                assert response is not None
                response.raise_for_status()
            time.sleep(self.retry_backoff_seconds * (2**attempt))

        assert response is not None
        data = response.json()
        ordered = sorted(data.get("data") or [], key=lambda item: int(item["index"]))
        vectors = [[float(value) for value in item["embedding"]] for item in ordered]
        if len(vectors) != len(texts) or any(
            len(vector) != self.embedding_dimension for vector in vectors
        ):
            raise ValueError("百炼返回的向量数量或向量维度不符合配置")
        token_count = int((data.get("usage") or {}).get("total_tokens") or 0)
        self.usage["requests"] += 1
        self.usage["prompt_tokens"] += token_count
        self.usage["total_tokens"] += token_count
        request_id = response.headers.get("x-request-id") or data.get("request_id")
        if request_id:
            self.request_ids.append(str(request_id))
        return vectors

    @staticmethod
    def _parse_json(content: str) -> dict:
        stripped = content.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, re.DOTALL)
        if fenced:
            stripped = fenced.group(1)
        value = json.loads(stripped)
        if not isinstance(value, dict):
            raise QwenStructuredOutputError("模型输出必须是 JSON 对象")
        return value

    def complete_json(
        self,
        role: ModelRole,
        messages: list[dict],
        schema: type[BaseModel] | None = None,
    ) -> dict:
        working_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(3):
            content = self.complete(role, working_messages, json_mode=True)
            try:
                parsed = self._parse_json(content)
                if schema is None:
                    return parsed
                return schema.model_validate(parsed).model_dump(mode="json")
            except (json.JSONDecodeError, QwenStructuredOutputError, ValidationError) as exc:
                last_error = exc
                if attempt == 2:
                    break
                working_messages.extend(
                    [
                        {"role": "assistant", "content": content},
                        {
                            "role": "user",
                            "content": "上一个输出无法通过 JSON Schema 校验。只返回合法 JSON 对象，不要使用 Markdown。",
                        },
                    ]
                )
        raise QwenStructuredOutputError(f"两次修复后仍无法解析结构化输出: {last_error}")

    def verify_evidence(self, *, statement: str, excerpt: str, stance: str) -> dict:
        return self.complete_json(
            "extractor",
            [
                {
                    "role": "system",
                    "content": (
                        "你是隔离上下文的证据核验器。判断原文是否支持、反对或限定观点；"
                        "不得使用原文以外的知识，只返回JSON。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "statement": statement,
                            "excerpt": excerpt,
                            "proposed_stance": stance,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            schema=EvidenceVerification,
        )
