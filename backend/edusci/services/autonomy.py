from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.domain.flow import FlowStage
from edusci.memory.models import AutonomousRunRecord, FlowEvent, Project, TaskRecord


_TERMINAL_RUN_STATUSES = ("completed", "failed", "canceled")


def find_active_autonomous_run(
    session: Session, project_id: str
) -> AutonomousRunRecord | None:
    return session.scalar(
        select(AutonomousRunRecord)
        .where(
            AutonomousRunRecord.project_id == project_id,
            AutonomousRunRecord.status.not_in(_TERMINAL_RUN_STATUSES),
        )
        .order_by(AutonomousRunRecord.created_at.desc())
        .limit(1)
    )


def find_latest_autonomous_run(
    session: Session, project_id: str
) -> AutonomousRunRecord | None:
    return session.scalar(
        select(AutonomousRunRecord)
        .where(AutonomousRunRecord.project_id == project_id)
        .order_by(AutonomousRunRecord.created_at.desc())
        .limit(1)
    )


def mark_autonomous_run_failed(
    session: Session, run_id: str, exc: Exception
) -> AutonomousRunRecord:
    session.rollback()
    run = require_autonomous_run(session, run_id)
    if run.status != "failed":
        run.status = "failed"
        run.error = {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "node": run.current_node,
        }
        if run.task_id:
            task = session.get(TaskRecord, run.task_id)
            if task is not None:
                task.status = "failed"
                task.retryable = True
                task.error = run.error
        session.add(run)
        session.commit()
        session.refresh(run)
    return run


def create_autonomous_run(
    session: Session,
    project: Project,
    config: dict | None = None,
    *,
    queued: bool = False,
) -> AutonomousRunRecord:
    if project.stage != FlowStage.IDEA.value:
        project.stage = FlowStage.IDEA.value
        project.route = None
        project.suggested_route = None
        project.scores = {}
        project.study_design = {}
        project.analysis_result = {}
        session.add(project)

    initial_status = "queued" if queued else "planning"
    task = TaskRecord(
        project_id=project.id,
        kind="autonomous_research",
        status="queued" if queued else "started",
    )
    session.add(task)
    session.flush()
    run = AutonomousRunRecord(
        project_id=project.id,
        task_id=task.id,
        status=initial_status,
        current_node=initial_status,
        config=config or {},
    )
    session.add(run)
    session.flush()
    session.add(
        FlowEvent(
            task_id=task.id,
            event_type="started",
            payload={
                "run_id": run.id,
                "node": initial_status,
                "message": "自治研究任务已创建",
                "progress": 0,
            },
        )
    )
    session.commit()
    session.refresh(run)
    return run


def require_autonomous_run(session: Session, run_id: str) -> AutonomousRunRecord:
    run = session.get(AutonomousRunRecord, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="自治研究任务不存在")
    return run


def request_cancellation(
    session: Session, run: AutonomousRunRecord
) -> AutonomousRunRecord:
    run.cancel_requested = True
    session.add(run)
    session.commit()
    session.refresh(run)
    return run
