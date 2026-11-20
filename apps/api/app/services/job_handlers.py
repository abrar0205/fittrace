"""Registered background-job handlers."""

from __future__ import annotations

from app.domain import models as m
from app.pipelines.measure import run_measurement_pipeline
from app.pipelines.mes_import import run_mes_import
from app.services.jobs import handler
from app.services.verification import execute_verification, mark_failed


@handler("verify_corrective_action")
def _verify(job: m.Job, progress) -> dict:
    vr_id = int(job.payload["verification_run_id"])
    try:
        return execute_verification(vr_id, progress)
    except Exception as e:
        if job.attempts >= job.max_attempts:
            mark_failed(vr_id, f"{type(e).__name__}: {e}")
        raise


@handler("pipeline_retry")
def _retry(job: m.Job, progress) -> dict:
    p = job.payload
    if p["pipeline"] == "mes_import":
        run_id = run_mes_import(p["source_uri"], p["dataset_key"], retry_of_id=p["retry_of_id"], job_id=job.id)
    elif p["pipeline"] == "gap_measurement":
        run_id = run_measurement_pipeline(p["dataset_key"], retry_of_id=p["retry_of_id"], job_id=job.id,
                                          progress=lambda f: progress(f, None))
    else:
        raise ValueError(f"unknown pipeline {p['pipeline']!r}")
    return {"pipeline_run_id": run_id}
