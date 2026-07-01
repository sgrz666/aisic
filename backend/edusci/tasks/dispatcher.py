from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from edusci.memory.models import FlowEvent, Project, TaskRecord
from edusci.tasks.jobs import execute_task


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
