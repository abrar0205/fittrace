"""PostgreSQL-backed job queue (``SELECT ... FOR UPDATE SKIP LOCKED``).

Chosen over Redis/RQ because every job already reads and writes PostgreSQL:
one fewer service to run, and job state is transactional with its results.
A worker is a separate process (``python -m app.worker``) or, for single-service
deployments, a thread inside the API (``FITTRACE_RUN_WORKER_IN_PROCESS=true``).
"""

from __future__ import annotations

import logging
import socket
import threading
import time
import traceback
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import APIError
from app.core.logging import log
from app.domain import models as m

logger = logging.getLogger("fittrace.jobs")
Handler = Callable[[m.Job, Callable[[float, str | None], None]], dict]
HANDLERS: dict[str, Handler] = {}


def handler(kind: str):
    def deco(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return deco


def enqueue(db: Session, kind: str, payload: dict, max_attempts: int = 2) -> m.Job:
    active = db.scalar(select(func.count()).select_from(m.Job).where(m.Job.status.in_(["queued", "running"]))) or 0
    if active >= get_settings().max_queued_jobs:
        raise APIError(429, "queue_full", f"{active} jobs are already queued or running; try again shortly")
    job = m.Job(kind=kind, payload=payload, max_attempts=max_attempts, status="queued")
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session) -> m.Job | None:
    row = db.execute(text(
        """
        UPDATE jobs SET status = 'running', started_at = now(), attempts = attempts + 1, message = :worker
         WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND run_after <= now()
                     ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING id
        """), {"worker": f"claimed by {socket.gethostname()}"}).first()
    db.commit()
    return db.get(m.Job, row[0]) if row else None


def run_one() -> bool:
    """Claim and execute one job. Returns False when the queue is empty."""
    from app.services import job_handlers  # noqa: F401 - registers handlers

    SessionLocal = get_sessionmaker()
    with SessionLocal() as db:
        job = claim_next(db)
        if job is None:
            return False
        job_id, kind = job.id, job.kind

    def progress(frac: float, msg: str | None = None) -> None:
        with SessionLocal() as s, s.begin():
            j = s.get(m.Job, job_id)
            if j:
                j.progress = round(max(0.0, min(1.0, frac)), 4)
                if msg:
                    j.message = msg

    log(logger, logging.INFO, "job started", job_id=job_id, kind=kind)
    try:
        fn = HANDLERS.get(kind)
        if fn is None:
            raise LookupError(f"no handler for job kind {kind!r}")
        with SessionLocal() as db:
            job = db.get(m.Job, job_id)
        result = fn(job, progress)  # type: ignore[arg-type]
        with SessionLocal() as db, db.begin():
            j = db.get(m.Job, job_id)
            j.status, j.result, j.progress, j.finished_at, j.error = "succeeded", result, 1.0, datetime.now(UTC), None
        log(logger, logging.INFO, "job succeeded", job_id=job_id, kind=kind)
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc(limit=5)
        with SessionLocal() as db, db.begin():
            j = db.get(m.Job, job_id)
            j.error = f"{type(e).__name__}: {e}\n{tb}"
            if j.attempts < j.max_attempts:
                j.status, j.run_after = "queued", datetime.now(UTC) + timedelta(seconds=5 * j.attempts)
                j.message = f"retrying after failure (attempt {j.attempts}/{j.max_attempts})"
            else:
                j.status, j.finished_at, j.message = "failed", datetime.now(UTC), "failed permanently"
        log(logger, logging.ERROR, "job failed", job_id=job_id, kind=kind, error=str(e))
    return True


def recover_stale(db: Session, older_than_s: int = 900) -> int:
    """Requeue jobs left 'running' by a crashed worker."""
    res = db.execute(text("""UPDATE jobs SET status='queued', message='requeued after worker loss'
                              WHERE status='running' AND started_at < now() - make_interval(secs => :s)
                                AND attempts < max_attempts"""), {"s": older_than_s})
    db.commit()
    return res.rowcount or 0


def worker_loop(stop: threading.Event | None = None) -> None:
    poll = get_settings().worker_poll_seconds
    with get_sessionmaker()() as db:
        recover_stale(db)
    while not (stop and stop.is_set()):
        try:
            busy = run_one()
        except Exception:  # noqa: BLE001 - keep the worker alive
            logger.exception("worker iteration failed")
            busy = False
        if not busy:
            time.sleep(poll)
