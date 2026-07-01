from __future__ import annotations

import re
from datetime import datetime, timezone

from edusci.autonomy.contracts import (
    DataRequirement,
    LiteratureQuery,
    ResearchPlan,
    VariableSpec,
)


_ENGLISH_ALIASES = {
    "AI发展": "artificial intelligence development",
    "大学生": "university students",
    "心理健康": "mental health",
    "人口变化": "population change",
    "学龄人口": "school-age population",
    "基础教育资源配置": "basic education resource allocation",
    "教育资源": "education resources",
    "AI 焦虑度": "AI anxiety",
    "AI焦虑": "AI anxiety",
    "专业": "academic major",
    "教师数": "number of teachers",
    "学校数": "number of schools",
}


class ResearchPlanner:
    def __init__(self, model_provider=None) -> None:
        self.model_provider = model_provider

    @staticmethod
    def _deduplicate_queries(queries: list[dict]) -> list[dict]:
        deduplicated: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for query in queries:
            normalized = " ".join(str(query.get("query", "")).lower().split())
            language = str(query.get("language", "zh"))
            if len(normalized) < 2 or (normalized, language) in seen:
                continue
            seen.add((normalized, language))
            deduplicated.append(
                {
                    "query": str(query["query"]).strip(),
                    "language": language,
                    "purpose": query.get("purpose", "broad"),
                }
            )
            if len(deduplicated) == 8:
                break
        return deduplicated

    @staticmethod
    def _fallback(idea_text: str) -> dict:
        known = [value for value in _ENGLISH_ALIASES if value in idea_text]
        if not known:
            known = [
                piece.strip()
                for piece in re.split(r"与|和|对|的影响|关系", idea_text)
                if len(piece.strip()) >= 2
            ][:4]
        if not known:
            known = [idea_text.strip("。")]
        english = [_ENGLISH_ALIASES.get(value, value) for value in known]
        current_year = datetime.now(timezone.utc).year
        return {
            "problem_statement": idea_text.strip("。"),
            "concepts": known,
            "variables": [
                {
                    "name": value,
                    "aliases_zh": [],
                    "aliases_en": [alias] if alias != value else [],
                }
                for value, alias in zip(known, english, strict=True)
            ],
            "population": "基础教育阶段" if "基础教育" in idea_text else "待确认",
            "geographies": ["CHN"],
            "time_range": {"start": max(1900, current_year - 10), "end": current_year},
            "literature_queries": [
                {"query": " ".join(known), "language": "zh", "purpose": "broad"},
                {"query": " ".join(english), "language": "en", "purpose": "broad"},
            ],
            "data_requirements": [
                {
                    "concept": alias,
                    "unit_hint": "",
                    "required": True,
                }
                for alias in english
            ],
        }

    @staticmethod
    def _ensure_bilingual(payload: dict, idea_text: str) -> dict:
        queries = ResearchPlanner._deduplicate_queries(
            list(payload.get("literature_queries") or [])
        )
        languages = {query["language"] for query in queries}
        fallback = ResearchPlanner._fallback(idea_text)
        for language in ("zh", "en"):
            if language not in languages:
                candidate = next(
                    query
                    for query in fallback["literature_queries"]
                    if query["language"] == language
                )
                queries.append(candidate)
        payload["literature_queries"] = ResearchPlanner._deduplicate_queries(queries)
        return payload

    def plan(self, idea_text: str) -> ResearchPlan:
        if self.model_provider is None:
            payload = self._fallback(idea_text)
        else:
            payload = self.model_provider.complete_json(
                "generation",
                [
                    {
                        "role": "system",
                        "content": (
                            "你是教育研究规划器。只返回 JSON，不声称已完成检索，不生成代码。"
                            "字段必须为 problem_statement、concepts、variables、population、"
                            "geographies、time_range、literature_queries、data_requirements。"
                            "literature_queries 同时包含中文和英文，最多 8 条。"
                        ),
                    },
                    {"role": "user", "content": idea_text},
                ],
            )
        payload = self._ensure_bilingual(dict(payload), idea_text)
        if not payload.get("variables"):
            payload["variables"] = [
                VariableSpec(name=value).model_dump()
                for value in payload.get("concepts", [])
            ]
        if "data_requirements" not in payload:
            payload["data_requirements"] = [
                DataRequirement(concept=value).model_dump()
                for value in payload.get("concepts", [])
            ]
        payload["literature_queries"] = [
            LiteratureQuery.model_validate(query).model_dump()
            for query in payload["literature_queries"]
        ]
        return ResearchPlan.model_validate(payload)
