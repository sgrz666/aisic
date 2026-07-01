from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.analysis.engine import analyze_dataframe, profile_dataframe
from edusci.analysis.engine_v2 import analyze_questionnaire
from edusci.analysis.provenance import classify_dataset_origin
from edusci.analysis.storage import LocalObjectStore
from edusci.domain.flow import FlowStage, transition_stage
from edusci.memory.models import (
    DatasetAssetRecord,
    DatasetDeclarationRecord,
    DatasetRecord,
    Project,
    TaskRecord,
)
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
    session.flush()
    session.add(
        DatasetDeclarationRecord(
            dataset_id=record.id,
            project_id=project.id,
            origin_type=classify_dataset_origin(record.file_name),
            source_name=record.file_name,
            confirmed=classify_dataset_origin(record.file_name) == "synthetic_demo",
        )
    )
    if project.stage == FlowStage.WAITING_FOR_DATA.value:
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.ANALYSIS).value
    session.add(project)
    session.commit()
    session.refresh(record)
    return record


def promote_public_dataset(
    session: Session, project: Project, asset: DatasetAssetRecord
) -> DatasetRecord:
    """Expose a validated autonomous asset to the controlled analysis service."""
    existing = session.scalar(
        select(DatasetRecord).where(
            DatasetRecord.project_id == project.id,
            DatasetRecord.storage_path == asset.storage_path,
        )
    )
    if existing is not None:
        return existing
    columns = list(asset.schema_json)
    record = DatasetRecord(
        project_id=project.id,
        file_name=f"public-{asset.id}.csv",
        content_type="text/csv",
        storage_path=asset.storage_path,
        row_count=asset.row_count,
        column_count=asset.column_count,
        data_schema={"columns": columns, "types": asset.schema_json},
        quality_report=asset.quality_report,
    )
    session.add(record)
    session.flush()
    session.add(
        DatasetDeclarationRecord(
            dataset_id=record.id,
            project_id=project.id,
            origin_type="public_official",
            source_name=record.file_name,
            confirmed=True,
        )
    )
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
        project.analysis_result.update(
            analyze_questionnaire(
                frame,
                (project.study_design or {}).get("questionnaire", {}),
            )
        )
        project.analysis_result["dataset_id"] = dataset.id
        project.analysis_result["quality_report"] = dataset.quality_report
        project.stage = transition_stage(FlowStage(project.stage), FlowStage.REPORT).value

    return _task(session, project, "analysis", calculate, task)
