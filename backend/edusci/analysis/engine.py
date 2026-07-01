from __future__ import annotations

import math
from typing import Any

import pandas as pd
from scipy import stats

PII_TOKENS = ("姓名", "学号", "手机号", "手机", "电话", "邮箱", "身份证", "name", "phone", "email")


def _json_number(value: Any) -> float | int | None:
    if pd.isna(value) or (isinstance(value, float) and not math.isfinite(value)):
        return None
    if isinstance(value, (int,)):
        return int(value)
    return float(value)


def profile_dataframe(frame: pd.DataFrame) -> dict:
    pii_columns = [
        str(column)
        for column in frame.columns
        if any(token.lower() in str(column).lower() for token in PII_TOKENS)
    ]
    missing_by_column = {str(k): int(v) for k, v in frame.isna().sum().items()}
    return {
        "rows": int(len(frame)),
        "columns": int(len(frame.columns)),
        "missing_cells": int(frame.isna().sum().sum()),
        "missing_by_column": missing_by_column,
        "duplicate_rows": int(frame.duplicated().sum()),
        "pii_columns": pii_columns,
        "column_types": {str(k): str(v) for k, v in frame.dtypes.items()},
    }


def analyze_dataframe(
    frame: pd.DataFrame, outcome_column: str | None = None, group_column: str | None = None
) -> dict:
    numeric = frame.select_dtypes(include="number")
    descriptive: dict[str, dict] = {}
    for column in numeric.columns:
        series = numeric[column].dropna()
        descriptive[str(column)] = {
            "count": int(series.count()),
            "mean": _json_number(series.mean()),
            "std": _json_number(series.std()),
            "min": _json_number(series.min()),
            "max": _json_number(series.max()),
        }

    correlations: dict[str, dict[str, float | None]] = {}
    if len(numeric.columns) >= 2:
        corr = numeric.corr(method="pearson")
        correlations = {
            str(row): {str(col): _json_number(value) for col, value in values.items()}
            for row, values in corr.to_dict(orient="index").items()
        }

    group_test: dict = {}
    if outcome_column and group_column:
        if outcome_column not in frame.columns or group_column not in frame.columns:
            raise ValueError("分析列不存在")
        clean = frame[[group_column, outcome_column]].dropna()
        labels = [str(value) for value in clean[group_column].drop_duplicates().tolist()]
        samples = [
            pd.to_numeric(clean.loc[clean[group_column].astype(str) == label, outcome_column]).dropna()
            for label in labels
        ]
        if len(samples) == 2:
            statistic, p_value = stats.ttest_ind(samples[0], samples[1], equal_var=False)
            method = "independent_t_test"
        elif len(samples) > 2:
            statistic, p_value = stats.f_oneway(*samples)
            method = "one_way_anova"
        else:
            raise ValueError("组间检验至少需要两个有效分组")
        group_test = {
            "method": method,
            "groups": labels,
            "statistic": _json_number(statistic),
            "p_value": _json_number(p_value),
            "significant_at_0_05": bool(p_value < 0.05),
        }

    return {
        "sample_size": int(len(frame)),
        "descriptive": descriptive,
        "correlations": correlations,
        "group_test": group_test,
        "limitations": ["统计结果仅适用于当前上传样本，不自动推断因果关系。"],
    }

