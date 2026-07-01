from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd


class LocalObjectStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, project_id: str, file_name: str, content: bytes) -> Path:
        safe_name = Path(file_name).name
        suffix = Path(safe_name).suffix.lower()
        if suffix not in {".csv", ".xlsx"}:
            raise ValueError("仅支持 CSV 或 XLSX 数据文件")
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("单文件不得超过 50 MB")
        directory = self.root / project_id
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4().hex}{suffix}"
        path.write_bytes(content)
        return path

    def save_pdf(self, project_id: str, file_name: str, content: bytes) -> Path:
        safe_name = Path(file_name).name
        if Path(safe_name).suffix.lower() != ".pdf":
            raise ValueError("文献摄入仅支持 PDF")
        if len(content) > 50 * 1024 * 1024:
            raise ValueError("单文件不得超过 50 MB")
        directory = self.root / project_id / "documents"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{uuid4().hex}.pdf"
        path.write_bytes(content)
        return path

    @staticmethod
    def read_dataframe(path: str | Path) -> pd.DataFrame:
        target = Path(path)
        if target.suffix.lower() == ".xlsx":
            return pd.read_excel(target)
        try:
            return pd.read_csv(target, encoding="utf-8-sig")
        except UnicodeDecodeError:
            return pd.read_csv(target, encoding="gb18030")
