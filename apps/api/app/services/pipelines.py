from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, not_found
from app.domain import models as m
from app.services import jobs
from app.services.common import paginate


def run_out(db: Session, r: m.PipelineRun) -> dict:
    ds = db.get(m.Dataset, r.dataset_id) if r.dataset_id else None
    dur = (r.finished_at - r.started_at).total_seconds() if r.finished_at else None
    return {"id": r.id, "pipeline": r.pipeline, "dataset_key": ds.key if ds else None, "source_uri": r.source_uri,
            "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at, "duration_s": dur,
            "records_in": r.records_in, "records_loaded": r.records_loaded, "records_rejected": r.records_rejected,
            "records_duplicate": r.records_duplicate, "records_skipped": r.records_skipped,
            "error_message": r.error_message, "retry_of_id": r.retry_of_id, "metrics": r.metrics or {},
            "params": r.params or {}}


def list_runs(db: Session, pipeline: str | None, status: str | None, page: int, page_size: int) -> dict:
    offset, limit = paginate(page, page_size, get_settings().page_size_max)
    q = select(m.PipelineRun)
    if pipeline:
        q = q.where(m.PipelineRun.pipeline == pipeline)
    if status:
        q = q.where(m.PipelineRun.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(q.order_by(m.PipelineRun.started_at.desc(), m.PipelineRun.id.desc()).offset(offset).limit(limit))
    return {"items": [run_out(db, r) for r in items], "total": total, "page": page, "page_size": page_size}


def run_detail(db: Session, run_id: int) -> dict:
    r = db.get(m.PipelineRun, run_id)
    if r is None:
        raise not_found("pipeline run", run_id)
    dq = [{"check_name": d.check_name, "passed": d.passed, "observed": d.observed}
          for d in db.scalars(select(m.DataQualityResult).where(m.DataQualityResult.pipeline_run_id == run_id))]
    imps = [{"file_name": i.file_name, "file_kind": i.file_kind, "sha256": i.sha256, "rows": i.rows}
            for i in db.scalars(select(m.DatasetImport).where(m.DatasetImport.pipeline_run_id == run_id))]
    # Group rejects by pattern: identifiers and numbers are masked so "unit SIM-00110 ..." rows collapse together.
    pattern = func.regexp_replace(m.PipelineError.reason, "[A-Z]+-[0-9]+|-?[0-9][0-9.]*", "#", "g").label("pattern")
    n = func.count().label("n")
    summary = [{"file_name": f, "field": fl, "reason": reason, "count": c} for f, fl, reason, c in db.execute(
        select(m.PipelineError.file_name, m.PipelineError.field, pattern, n)
        .where(m.PipelineError.pipeline_run_id == run_id)
        .group_by(m.PipelineError.file_name, m.PipelineError.field, pattern).order_by(n.desc()).limit(30))]
    return {**run_out(db, r), "data_quality": dq, "imports": imps, "error_summary": summary}


def run_errors(db: Session, run_id: int, page: int, page_size: int) -> dict:
    if db.get(m.PipelineRun, run_id) is None:
        raise not_found("pipeline run", run_id)
    offset, limit = paginate(page, page_size, get_settings().page_size_max)
    q = select(m.PipelineError).where(m.PipelineError.pipeline_run_id == run_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(q.order_by(m.PipelineError.file_name, m.PipelineError.row_number, m.PipelineError.id)
                       .offset(offset).limit(limit))
    return {"items": [{"id": e.id, "file_name": e.file_name, "row_number": e.row_number, "field": e.field,
                       "reason": e.reason, "raw": e.raw} for e in items], "total": total, "page": page,
            "page_size": page_size}


def retry(db: Session, run_id: int) -> dict:
    r = db.get(m.PipelineRun, run_id)
    if r is None:
        raise not_found("pipeline run", run_id)
    if r.status != "failed":
        raise APIError(409, "not_failed", "only failed runs can be retried")
    ds_key = (r.params or {}).get("dataset_key")
    job = jobs.enqueue(db, "pipeline_retry", {"pipeline": r.pipeline, "source_uri": r.source_uri, "dataset_key": ds_key,
                                              "retry_of_id": r.id}, max_attempts=1)
    db.commit()
    return {c: getattr(job, c) for c in ("id", "kind", "status", "progress", "message", "error", "attempts",
                                         "max_attempts", "result", "created_at", "started_at", "finished_at")}
