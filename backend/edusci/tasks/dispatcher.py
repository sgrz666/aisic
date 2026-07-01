from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from edusci.memory.models import AutonomousRunRecord, FlowEvent, Project, TaskRecord
from edusci.tasks.jobs import execute_autonomous_run, execute_task


def enqueue_task(
    session: Session,
    queue,
    database_url: str,
    storage_root: str | Path,
    project: Project,
    kind: str,
    payload: dict | None = None,
) -> TaskRecord:
    task = TaskRecord(
        project_id=project.id,
        kind=kind,
        status="queued",
        input_payload=payload or {},
    )
    session.add(task)
    session.flush()
    session.add(
        FlowEvent(
            task_id=task.id,
            event_type="started",
            payload={"kind": kind, "phase": "queued"},
        )
    )
    session.commit()
    try:
        queue.enqueue(
            execute_task,
            task.id,
            database_url,
            str(storage_root),
            job_id=task.id,
            job_timeout="30m",
        )
    except Exception as exc:
        task.status = "failed"
        task.retryable = True
        task.error = {"code": "QUEUE_UNAVAILABLE", "message": str(exc)}
        session.add(task)
        session.add(
            FlowEvent(task_id=task.id, event_type="failed", payload=task.error)
        )
        session.commit()
        raise
    return task


def enqueue_autonomous_run(
    session: Session,
    queue,
    database_url: str,
    storage_root: str | Path,
    run: AutonomousRunRecord,
    *,
    action: str = "start",
    dataset_id: str | None = None,
) -> AutonomousRunRecord:
    run.status = "queued"
    if run.task_id:
        task = session.get(TaskRecord, run.task_id)
        if task:
            task.status = "queued"
    session.add(run)
    session.commit()
    try:
        queue.enqueue(
            execute_autonomous_run,
            run.id,
            database_url,
            str(storage_root),
            action,
            dataset_id,
            job_id=run.id,
            job_timeout="30m",
        )
    except Exception as exc:
        run.status = "failed"
        run.error = {"code": "QUEUE_UNAVAILABLE", "message": str(exc)}
        session.add(run)
        session.commit()
        raise
    return run
