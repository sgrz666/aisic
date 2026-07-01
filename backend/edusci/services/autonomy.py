from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from edusci.memory.models import AutonomousRunRecord, Project, TaskRecord


def create_autonomous_run(
    session: Session, project: Project, config: dict | None = None
) -> AutonomousRunRecord:
    task = TaskRecord(project_id=project.id, kind="autonomous_research", status="started")
    session.add(task)
    session.flush()
    run = AutonomousRunRecord(
        project_id=project.id,
        task_id=task.id,
        status="planning",
        current_node="planning",
        config=config or {},
    )
    session.add(run)
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
