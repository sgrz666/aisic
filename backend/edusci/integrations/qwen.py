from __future__ import annotations

import json
import re
from typing import Literal

import httpx

ModelRole = Literal["generation", "review"]


class QwenConfigurationError(ValueError):
    pass


class QwenStructuredOutputError(ValueError):
    pass


class QwenProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        generation_model: str = "qwen-plus",
        review_model: str = "qwen-max",
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise QwenConfigurationError("请配置 DASHSCOPE_API_KEY")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.generation_model = generation_model
        self.review_model = review_model
        self.client = client or httpx.Client(timeout=90)

    def _model(self, role: ModelRole) -> str:
        return self.review_model if role == "review" else self.generation_model

    def complete(self, role: ModelRole, messages: list[dict], json_mode: bool = False) -> str:
        payload: dict = {"model": self._model(role), "messages": messages, "temperature": 0.2}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        response.raise_for_status()
        return str(response.json()["choices"][0]["message"]["content"])

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

    def complete_json(self, role: ModelRole, messages: list[dict]) -> dict:
        working_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(3):
            content = self.complete(role, working_messages, json_mode=True)
            try:
                return self._parse_json(content)
            except (json.JSONDecodeError, QwenStructuredOutputError) as exc:
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

