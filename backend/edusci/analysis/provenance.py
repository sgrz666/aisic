from __future__ import annotations

from typing import Literal

DatasetOrigin = Literal[
    "real_collected", "public_official", "synthetic_demo", "unknown"
]


def classify_dataset_origin(
    file_name: str, declared_origin: DatasetOrigin | None = None
) -> DatasetOrigin:
    if declared_origin is not None:
        return declared_origin
    lowered = file_name.lower()
    if any(token in lowered for token in ("模拟", "synthetic", "demo", "示例", "fake")):
        return "synthetic_demo"
    return "unknown"
