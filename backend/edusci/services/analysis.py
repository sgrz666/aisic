from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from edusci.analysis.engine import analyze_dataframe, profile_dataframe
from edusci.analysis.storage import LocalObjectStore
from edusci.domain.flow import FlowStage, transition_stage
from edusci.memory.models import DatasetRecord, Project, TaskRecord
from edusci.services.projects import _task


def save_dataset(
    session: Session,
    store: LocalObjectStore,
    project: Project,
    file_name: str,
    content_type: str,
    content: bytes,
) -> DatasetRecord:
    allowed_stages = {FlowStage.WAITING_FOR_DATA.value, FlowStage.ANALYSIS.value}
    if project.stage not in allowed_stages:
        raise HTTPException(status_code=409, detail="当前项目不在数据接收或分析阶段")
    try:
        path = store.save(project.id, file_name, content)
        frame = store.read_dataframe(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = profile_dataframe(frame)
    record = DatasetRecord(
        project_id=project.id,
        file_name=Path(file_name).name,
        content_type=content_type,
        storage_path=str(path),
        row_count=profile["rows"],
        column_count=profile["columns"],
        data_schema={"columns": [str(column) for column in frame.columns]},
        quality_report=profile,
    )
    session.add(record)
    if project.stage == FlowStage.WAITING_FOR_DATA.value:
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.ANALYSIS).value
    session.add(project)
    session.commit()
    session.refresh(record)
    return record


def run_analysis(
    session: Session,
    store: LocalObjectStore,
    project: Project,
    dataset_id: str,
    outcome_column: str | None,
    group_column: str | None,
    task: TaskRecord | None = None,
):
    def calculate() -> None:
        if project.stage != FlowStage.ANALYSIS.value:
            raise ValueError("当前阶段不能运行统计分析")
        dataset = session.get(DatasetRecord, dataset_id)
        if dataset is None or dataset.project_id != project.id:
            raise ValueError("数据集不存在或不属于当前项目")
        frame = store.read_dataframe(dataset.storage_path)
        project.analysis_result = analyze_dataframe(frame, outcome_column, group_column)
        project.analysis_result["dataset_id"] = dataset.id
        project.analysis_result["quality_report"] = dataset.quality_report
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.REPORT).value

    return _task(session, project, "analysis", calculate, task)
