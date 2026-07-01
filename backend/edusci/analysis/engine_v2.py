from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats


def _matched_columns(frame: pd.DataFrame, item_ids: list[str]) -> list[str]:
    columns: list[str] = []
    for item_id in item_ids:
        exact_or_prefixed = [
            str(column)
            for column in frame.columns
            if str(column) == item_id or str(column).startswith(f"{item_id}_")
        ]
        if exact_or_prefixed:
            columns.append(exact_or_prefixed[0])
    return columns


def _cronbach_alpha(values: pd.DataFrame) -> float | None:
    clean = values.dropna()
    item_count = len(clean.columns)
    if item_count < 2 or len(clean) < 2:
        return None
    item_variance = clean.var(axis=0, ddof=1).sum()
    total_variance = clean.sum(axis=1).var(ddof=1)
    if not total_variance or math.isnan(total_variance):
        return None
    return float(item_count / (item_count - 1) * (1 - item_variance / total_variance))


def _correlation_ci(r_value: float, n: int) -> list[float | None]:
    if n <= 3 or abs(r_value) >= 1:
        return [None, None]
    z_value = np.arctanh(r_value)
    margin = stats.norm.ppf(0.975) / math.sqrt(n - 3)
    return [float(np.tanh(z_value - margin)), float(np.tanh(z_value + margin))]


def analyze_questionnaire(frame: pd.DataFrame, questionnaire: dict | None = None) -> dict:
    working = frame.copy()
    variable_map = (questionnaire or {}).get("variable_item_map", {})
    derived_scales: dict[str, dict] = {}
    reliability: dict[str, dict] = {}

    for scale_name, item_ids in variable_map.items():
        columns = _matched_columns(working, list(item_ids))
        if len(columns) < 2:
            continue
        numeric = working[columns].apply(pd.to_numeric, errors="coerce")
        working[scale_name] = numeric.mean(axis=1)
        alpha = _cronbach_alpha(numeric)
        item_correlation = float(numeric.corr().iloc[0, 1]) if len(columns) == 2 else None
        spearman_brown = (
            float(2 * item_correlation / (1 + item_correlation))
            if item_correlation is not None and item_correlation > -1
            else None
        )
        derived_scales[scale_name] = {
            "items": columns,
            "valid_n": int(working[scale_name].notna().sum()),
            "mean": float(working[scale_name].mean()),
            "std": float(working[scale_name].std()),
        }
        reliability[scale_name] = {
            "cronbach_alpha": alpha,
            "item_correlation": item_correlation,
            "spearman_brown": spearman_brown,
        }

    scale_names = list(derived_scales)
    correlation_tests: list[dict] = []
    for left_index, left in enumerate(scale_names):
        for right in scale_names[left_index + 1 :]:
            clean = working[[left, right]].dropna()
            if len(clean) < 3 or clean[left].nunique() < 2 or clean[right].nunique() < 2:
                continue
            r_value, p_value = stats.pearsonr(clean[left], clean[right])
            correlation_tests.append(
                {
                    "method": "pearson_correlation",
                    "variables": [left, right],
                    "n": int(len(clean)),
                    "estimate": float(r_value),
                    "p_value": float(p_value),
                    "confidence_interval_95": _correlation_ci(float(r_value), len(clean)),
                    "effect_size": abs(float(r_value)),
                }
            )

    return {
        "sample_size": int(len(frame)),
        "derived_scales": derived_scales,
        "reliability": reliability,
        "correlation_tests": correlation_tests,
        "analysis_plan": {
            "methods": ["scale_construction", "reliability", "pearson_correlation"],
            "alpha": 0.05,
        },
    }
