from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import select

from edusci.analysis.storage import LocalObjectStore
from edusci.api.schemas import SourceInput
from edusci.integrations.qwen import QwenProvider
from edusci.integrations.retrieval import OpenResearchRetriever
from edusci.memory.database import build_session_factory
from edusci.memory.models import DatasetRecord, Project, TaskRecord
from edusci.services.analysis import run_analysis
from edusci.services.projects import run_evidence_build, run_gate, run_idea_parse
from edusci.services.reporting import run_report, run_review
from edusci.services.study import run_study_design


def _provider():
    api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
    if not api_key:
        return None
    return QwenProvider(
        api_key=api_key,
        base_url=os.getenv(
            "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        generation_model=os.getenv("QWEN_GENERATION_MODEL", "qwen-plus"),
        review_model=os.getenv("QWEN_REVIEW_MODEL", "qwen-max"),
    )


def execute_task(task_id: str, database_url: str, storage_root: str) -> None:
    session_factory = build_session_factory(database_url)
    with session_factory() as session:
        task = session.get(TaskRecord, task_id)
        if task is None or task.status == "canceled":
            return
        project = session.get(Project, task.project_id)
        if project is None:
            raise ValueError("异步任务所属项目不存在")
        payload = task.input_payload or {}
        provider = _provider()

        if task.kind == "idea_parse":
            run_idea_parse(session, project, provider, task)
        elif task.kind == "evidence_build":
            sources = [SourceInput.model_validate(item) for item in payload.get("sources", [])]
            retriever = (
                OpenResearchRetriever()
                if os.getenv("ENABLE_LIVE_RETRIEVAL", "false").lower() == "true"
                else None
            )
            run_evidence_build(session, project, sources, retriever, task)
        elif task.kind == "gate":
            run_gate(session, project, task)
        elif task.kind == "study_design":
            run_study_design(session, project, task)
        elif task.kind == "analysis":
            dataset_id = payload.get("dataset_id")
            if not dataset_id:
                dataset = session.scalar(
                    select(DatasetRecord)
                    .where(DatasetRecord.project_id == project.id)
                    .order_by(DatasetRecord.created_at.desc())
                )
                dataset_id = dataset.id if dataset else None
            if not dataset_id:
                raise ValueError("分析任务缺少数据集")
            run_analysis(
                session,
                LocalObjectStore(Path(storage_root)),
                project,
                dataset_id,
                payload.get("outcome_column"),
                payload.get("group_column"),
                task,
            )
        elif task.kind == "report":
            run_report(session, project, task)
        elif task.kind == "review":
            run_review(session, project, provider, task)
        else:
            raise ValueError(f"未知任务类型: {task.kind}")
