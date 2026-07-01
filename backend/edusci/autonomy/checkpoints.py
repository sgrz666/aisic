from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from edusci.autonomy.contracts import CheckpointOutput
from edusci.memory.models import (
    AutonomousRunRecord,
    FlowEvent,
    NodeCheckpointRecord,
)


def input_hash(node_name: str, payload: dict) -> str:
    canonical = json.dumps(
        {"node": node_name, "payload": payload},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class CheckpointStore:
    def __init__(self, session: Session, run: AutonomousRunRecord) -> None:
        self.session = session
        self.run = run

    def run_node(
        self,
        node_name: str,
        payload: dict,
        callback: Callable[[], dict],
        *,
        progress: int,
        message: str,
    ) -> CheckpointOutput:
        digest = input_hash(node_name, payload)
        checkpoint = self.session.scalar(
            select(NodeCheckpointRecord).where(
                NodeCheckpointRecord.run_id == self.run.id,
                NodeCheckpointRecord.node_name == node_name,
                NodeCheckpointRecord.input_hash == digest,
            )
        )
        if checkpoint is not None and checkpoint.status == "completed":
            return CheckpointOutput(
                node_name=node_name,
                input_hash=digest,
                output=checkpoint.output,
                reused=True,
            )

        if checkpoint is None:
            checkpoint = NodeCheckpointRecord(
                run_id=self.run.id,
                node_name=node_name,
                input_hash=digest,
                status="running",
            )
            self.session.add(checkpoint)
        else:
            checkpoint.status = "running"
            checkpoint.error = {}
            checkpoint.attempt_count += 1
            checkpoint.started_at = datetime.now(UTC)

        self.run.current_node = node_name
        self.session.add(self.run)
        self._event("progress", node_name, message, progress)
        self.session.commit()

        try:
            output = callback()
            checkpoint.status = "completed"
            checkpoint.output = output
            checkpoint.completed_at = datetime.now(UTC)
            self._event("node_completed", node_name, message, progress)
            self.session.add(checkpoint)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            checkpoint = self.session.scalar(
                select(NodeCheckpointRecord).where(
                    NodeCheckpointRecord.run_id == self.run.id,
                    NodeCheckpointRecord.node_name == node_name,
                    NodeCheckpointRecord.input_hash == digest,
                )
            )
            if checkpoint is not None:
                checkpoint.status = "failed"
                checkpoint.error = {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                    "node": node_name,
                }
                self.session.add(checkpoint)
            self.session.commit()
            raise

        return CheckpointOutput(
            node_name=node_name,
            input_hash=digest,
            output=output,
            reused=False,
        )

    def _event(
        self, event_type: str, node: str, message: str, progress: int
    ) -> None:
        if not self.run.task_id:
            return
        self.session.add(
            FlowEvent(
                task_id=self.run.task_id,
                event_type=event_type,
                payload={
                    "run_id": self.run.id,
                    "node": node,
                    "message": message,
                    "progress": progress,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        )
