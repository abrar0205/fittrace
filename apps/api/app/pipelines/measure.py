"""Pipeline: run the gap algorithm over inspection images and persist results.

Idempotent and resumable: an image that already has a *pipeline* run with the
active algorithm version and parameters is skipped. Results are committed in
batches, so an interrupted run resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import cv2
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import log
from app.domain import models as m
from fittrace.vision.gap import ALGORITHM_NAME, ALGORITHM_VERSION, GapParams, measure_gap
from fittrace.vision.tolerance import ToleranceSpec

logger = logging.getLogger("fittrace.etl.measure")
PIPELINE = "gap_measurement"


def params_hash(p: GapParams) -> str:
    return hashlib.sha256(json.dumps(p.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


def ensure_algorithm(db: Session, p: GapParams) -> m.AlgorithmVersion:
    h = params_hash(p)
    db.execute(insert(m.AlgorithmVersion).values(name=ALGORITHM_NAME, version=ALGORITHM_VERSION, params_hash=h,
                                                 params=p.to_dict()).on_conflict_do_nothing())
    av = db.scalar(select(m.AlgorithmVersion).where(m.AlgorithmVersion.name == ALGORITHM_NAME,
                                                    m.AlgorithmVersion.version == ALGORITHM_VERSION,
                                                    m.AlgorithmVersion.params_hash == h))
    assert av is not None
    return av


def resolve_image_path(storage_path: str) -> Path:
    base = get_settings().data_dir.resolve()
    p = (base / storage_path).resolve()
    if not p.is_relative_to(base):
        raise ValueError("image path escapes data directory")
    return p


def tolerance_for(db: Session, location_id: int, at: datetime) -> m.ToleranceSpecification:
    spec = db.scalar(select(m.ToleranceSpecification)
                     .where(m.ToleranceSpecification.location_id == location_id, m.ToleranceSpecification.valid_from <= at)
                     .order_by(m.ToleranceSpecification.valid_from.desc(), m.ToleranceSpecification.version.desc()).limit(1))
    if spec is None:
        raise LookupError(f"no tolerance specification valid at {at} for location {location_id}")
    return spec


def calibration_scale(cal: m.CalibrationRecord | None, at: datetime) -> tuple[float | None, str | None]:
    """Return (mm_per_px, problem). Expired or future calibrations are not used."""
    if cal is None:
        return None, "no calibration linked"
    if cal.valid_from > at:
        return None, f"calibration {cal.reference} not valid before {cal.valid_from.isoformat()}"
    if cal.valid_to is not None and cal.valid_to < at:
        return None, f"calibration {cal.reference} expired {cal.valid_to.isoformat()}"
    return cal.mm_per_px, None


def measure_image(db: Session, image: m.InspectionImage, av: m.AlgorithmVersion, params: GapParams, trigger: str,
                  pipeline_run_id: int | None = None) -> m.InspectionRun:
    """Measure one image and persist an inspection run (+ measurement when ok)."""
    path = resolve_image_path(image.storage_path)
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    cal = db.get(m.CalibrationRecord, image.calibration_id) if image.calibration_id else None
    scale, cal_problem = calibration_scale(cal, image.captured_at)
    if img is None:
        run = m.InspectionRun(image_id=image.id, algorithm_version_id=av.id, trigger=trigger, status="failed",
                              failure_code="unreadable_image", failure_message=f"could not read {image.storage_path}",
                              duration_ms=0.0, flags=[], diagnostics={}, overlay={}, pipeline_run_id=pipeline_run_id)
        db.add(run)
        db.flush()
        return run
    res = measure_gap(img, scale, params)
    diag = dict(res.diagnostics)
    if cal_problem:
        diag["calibration_problem"] = cal_problem
    diag["calibration_reference"] = cal.reference if cal else None
    run = m.InspectionRun(
        image_id=image.id, algorithm_version_id=av.id, trigger=trigger, status="ok" if res.ok else "failed",
        failure_code=res.failure_code, failure_message=res.failure_message, duration_ms=res.duration_ms,
        flags=res.flags, diagnostics=diag, overlay=res.overlay, pipeline_run_id=pipeline_run_id)
    db.add(run)
    db.flush()
    if res.ok:
        spec = tolerance_for(db, image.location_id, image.captured_at)
        status, dev = ToleranceSpec(spec.nominal_mm, spec.lower_tol_mm, spec.upper_tol_mm).evaluate(res.gap_mm)
        db.add(m.Measurement(run_id=run.id, location_id=image.location_id, tolerance_spec_id=spec.id,
                             gap_px=res.gap_px, gap_mm=res.gap_mm, std_error_mm=res.std_error_mm, deviation_mm=dev,
                             angle_deg=res.angle_deg, calibrated=res.calibrated, status=status.value))
        db.flush()
    return run


def run_measurement_pipeline(dataset_key: str, params: GapParams | None = None, batch: int = 100,
                             job_id: int | None = None, retry_of_id: int | None = None, progress=None) -> int:
    p = params or GapParams()
    SessionLocal = get_sessionmaker()
    t0 = time.perf_counter()
    with SessionLocal() as db:
        ds = db.scalar(select(m.Dataset).where(m.Dataset.key == dataset_key))
        run = m.PipelineRun(pipeline=PIPELINE, dataset_id=ds.id if ds else None, status="running",
                            params={"dataset_key": dataset_key, "algorithm": ALGORITHM_NAME, "version": ALGORITHM_VERSION,
                                    "gap_params": p.to_dict()}, job_id=job_id, retry_of_id=retry_of_id)
        db.add(run)
        db.commit()
        run_id = run.id
    loaded = skipped = failed_meas = errors = total = 0
    status, err = "succeeded", None
    error_rows: list[dict] = []
    try:
        if ds is None:
            raise LookupError(f"dataset {dataset_key!r} not found")
        with SessionLocal() as db:
            av = ensure_algorithm(db, p)
            db.commit()
            done_ids = set(db.scalars(select(m.InspectionRun.image_id).where(
                m.InspectionRun.algorithm_version_id == av.id, m.InspectionRun.trigger == "pipeline")))
            ids = list(db.scalars(select(m.InspectionImage.id).where(m.InspectionImage.dataset_id == ds.id)
                                  .order_by(m.InspectionImage.captured_at, m.InspectionImage.id)))
        total = len(ids)
        todo = [i for i in ids if i not in done_ids]
        skipped = total - len(todo)
        for start in range(0, len(todo), batch):
            chunk = todo[start : start + batch]
            with SessionLocal() as db, db.begin():
                av = db.get(m.AlgorithmVersion, av.id)
                for img in db.scalars(select(m.InspectionImage).where(m.InspectionImage.id.in_(chunk))):
                    try:
                        with db.begin_nested():
                            r = measure_image(db, img, av, p, "pipeline", run_id)
                            img.current_run_id = r.id
                        if r.status == "ok":
                            loaded += 1
                        else:
                            failed_meas += 1
                    except Exception as e:  # noqa: BLE001 - isolate per-image failures
                        errors += 1
                        error_rows.append({"file_name": img.storage_path, "field": None, "reason": f"{type(e).__name__}: {e}"})
            if progress:
                progress((start + len(chunk)) / max(1, len(todo)))
        if total and skipped == total:
            status = "skipped"
    except Exception as e:  # noqa: BLE001
        status, err = "failed", f"{type(e).__name__}: {e}"
        logger.exception("measurement pipeline failed")
    with SessionLocal() as db, db.begin():
        run = db.get(m.PipelineRun, run_id)
        assert run is not None
        run.status, run.error_message, run.finished_at = status, err, datetime.now(UTC)
        run.records_in, run.records_loaded, run.records_skipped = total, loaded + failed_meas, skipped
        run.records_rejected = errors
        run.metrics = {"duration_s": round(time.perf_counter() - t0, 3), "measured_ok": loaded,
                       "measurement_failures": failed_meas, "processing_errors": errors}
        for e in error_rows:
            db.add(m.PipelineError(pipeline_run_id=run_id, file_name=e["file_name"], row_number=None, field=e["field"],
                                   reason=e["reason"], raw={}))
    log(logger, logging.INFO, "measurement pipeline finished", run_id=run_id, status=status, measured=loaded,
        failures=failed_meas, skipped=skipped)
    return run_id


def current_measurements_query(dataset_id: int, location_id: int | None = None):
    q = (select(m.InspectionImage, m.InspectionRun, m.Measurement)
         .join(m.InspectionRun, m.InspectionRun.id == m.InspectionImage.current_run_id)
         .outerjoin(m.Measurement, m.Measurement.run_id == m.InspectionRun.id)
         .where(m.InspectionImage.dataset_id == dataset_id))
    if location_id is not None:
        q = q.where(and_(m.InspectionImage.location_id == location_id))
    return q
