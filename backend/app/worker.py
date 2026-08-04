"""Small durable worker process used by local Compose and staging smoke tests."""

from __future__ import annotations

import os
import signal
import time

from sqlalchemy import select

from app.db import SessionLocal, set_workspace_scope
from app.models import Execution, Workspace
from app.services.runtime import advance_execution, dispatch_outbox, recover_stale_claims


STOP = False


def _stop(_: int, __: object) -> None:
    global STOP
    STOP = True


def run_once(worker_id: str) -> int:
    processed = 0
    db = SessionLocal()
    try:
        workspaces = db.scalars(select(Workspace).order_by(Workspace.id)).all()
        for workspace in workspaces:
            set_workspace_scope(db, workspace.id)
            recover_stale_claims(db, workspace_id=workspace.id)
            dispatch_outbox(db, workspace_id=workspace.id, worker_id=worker_id, limit=20)
            executions = db.scalars(
                select(Execution)
                .where(
                    Execution.workspace_id == workspace.id,
                    Execution.status.in_(("queued", "running")),
                )
                .order_by(Execution.created_at)
                .limit(20)
                .with_for_update(skip_locked=True)
            ).all()
            for execution in executions:
                if advance_execution(db, execution, worker_id=worker_id, max_steps=1):
                    processed += 1
            db.commit()
    finally:
        db.close()
    return processed


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker_id = os.environ.get("RUNTIME_WORKER_ID", "runtime-worker")
    while not STOP:
        try:
            run_once(worker_id)
        except Exception:
            # The next loop retries after a bounded delay. Details stay out of
            # stdout so provider responses and configuration cannot leak.
            time.sleep(2)
        time.sleep(1)


if __name__ == "__main__":
    main()
