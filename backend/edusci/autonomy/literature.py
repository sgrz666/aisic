from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from edusci.autonomy.contracts import (
    LiteratureCandidate,
    LiteratureDiscoveryResult,
    LiteratureQuery,
    SearchAttemptData,
)


def _normalized_title(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def _evidence_type(text: str) -> str:
    lowered = text.lower()
    if any(term in lowered for term in ("scale", "measurement", "量表", "测量")):
        return "measurement"
    if any(term in lowered for term in ("method", "experiment", "方法", "实验")):
        return "method"
    if any(term in lowered for term in ("contradict", "counter", "相反", "冲突")):
        return "counter"
    if any(term in lowered for term in ("theory", "framework", "理论", "框架")):
        return "theory"
    return "general"


class LiteratureScout:
    def __init__(
        self,
        adapters: list,
        max_rounds: int = 3,
        max_results_per_query: int = 10,
    ) -> None:
        self.adapters = adapters
        self.max_rounds = max(1, min(max_rounds, 3))
        self.max_results_per_query = max(1, min(max_results_per_query, 50))

    @staticmethod
    def _score(raw: dict, concepts: list[str]) -> int:
        haystack = f"{raw.get('title', '')} {raw.get('abstract', '')}".lower()
        normalized_concepts = [concept.lower().strip() for concept in concepts if concept.strip()]
        matches = sum(concept in haystack for concept in normalized_concepts)
        relevance = round(45 * matches / max(1, len(normalized_concepts)))
        completeness = 20 if len(str(raw.get("abstract", "")).strip()) >= 40 else 0
        traceability = 20 if raw.get("doi") or str(raw.get("url", "")).startswith("https://") else 0
        year = raw.get("year")
        current_year = datetime.now(timezone.utc).year
        freshness = 10 if isinstance(year, int) and year >= current_year - 5 else 5 if year else 0
        citation_signal = 5 if int(raw.get("citation_count") or 0) > 0 else 0
        return min(100, relevance + completeness + traceability + freshness + citation_signal)

    @classmethod
    def _candidate(cls, raw: dict, source: str, concepts: list[str]) -> LiteratureCandidate:
        abstract = str(raw.get("abstract") or "").strip()
        doi = str(raw.get("doi") or "").lower().strip()
        title = str(raw.get("title") or "未命名文献").strip()
        source_id = str(raw.get("source_id") or doi or _normalized_title(title))
        exclusion = "" if len(abstract) >= 40 else "abstract_too_short"
        return LiteratureCandidate(
            source=source,
            source_id=source_id,
            title=title,
            abstract=abstract,
            doi=doi,
            authors=list(raw.get("authors") or []),
            year=raw.get("year"),
            url=str(raw.get("url") or (f"https://doi.org/{doi}" if doi else "")),
            license_url=str(raw.get("license_url") or ""),
            citation_count=int(raw.get("citation_count") or 0),
            source_title=str(raw.get("source_title") or ""),
            volume=str(raw.get("volume") or ""),
            issue=str(raw.get("issue") or ""),
            pages=str(raw.get("pages") or ""),
            publisher=str(raw.get("publisher") or ""),
            reference_type=str(raw.get("reference_type") or "J"),
            evidence_type=_evidence_type(f"{title} {abstract}"),
            relevance_score=cls._score(raw, concepts),
            exclusion_reason=exclusion,
        )

    @staticmethod
    def _dedup_key(candidate: LiteratureCandidate) -> str:
        if candidate.doi:
            return f"doi:{candidate.doi.lower()}"
        return f"title:{_normalized_title(candidate.title)}:{candidate.year or ''}"

    def discover(
        self,
        queries: list[LiteratureQuery],
        concepts: list[str],
    ) -> LiteratureDiscoveryResult:
        candidates: dict[str, LiteratureCandidate] = {}
        attempts: list[SearchAttemptData] = []
        stagnant_rounds = 0
        stop_reason = "max_rounds"
        rounds_completed = 0

        for round_number in range(1, self.max_rounds + 1):
            rounds_completed = round_number
            count_before = len(candidates)
            for adapter in self.adapters:
                source = str(getattr(adapter, "name", adapter.__class__.__name__))
                for query in queries:
                    started = time.perf_counter()
                    error = ""
                    raw_results: list[dict] = []
                    try:
                        raw_results = adapter.search(query.query, self.max_results_per_query)
                    except Exception as exc:
                        error = str(exc)
                    attempts.append(
                        SearchAttemptData(
                            source=source,
                            query=query.query,
                            round_number=round_number,
                            result_count=len(raw_results),
                            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
                            error=error,
                        )
                    )
                    for raw in raw_results:
                        candidate = self._candidate(raw, source, concepts)
                        key = self._dedup_key(candidate)
                        previous = candidates.get(key)
                        if previous is None or candidate.relevance_score > previous.relevance_score:
                            candidates[key] = candidate

            if round_number == 3 and candidates:
                seed = max(candidates.values(), key=lambda item: item.relevance_score)
                for adapter in self.adapters:
                    related = getattr(adapter, "related", None)
                    if related is None:
                        continue
                    try:
                        raw_related = related(seed.source_id, self.max_results_per_query)
                    except Exception:
                        continue
                    for raw in raw_related:
                        candidate = self._candidate(
                            raw,
                            str(getattr(adapter, "name", adapter.__class__.__name__)),
                            concepts,
                        )
                        candidates.setdefault(self._dedup_key(candidate), candidate)

            pass_candidates = [item for item in candidates.values() if not item.exclusion_reason]
            evidence_types = {item.evidence_type for item in pass_candidates}
            if len(pass_candidates) >= 6 and len(evidence_types) >= 3:
                stop_reason = "coverage_sufficient"
                break
            if len(candidates) == count_before:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            if stagnant_rounds >= 2:
                stop_reason = "no_new_evidence"
                break

        ordered = sorted(
            candidates.values(),
            key=lambda item: (not item.exclusion_reason, item.relevance_score, item.citation_count),
            reverse=True,
        )
        return LiteratureDiscoveryResult(
            candidates=ordered,
            attempts=attempts,
            rounds_completed=rounds_completed,
            stop_reason=stop_reason,
        )
