from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, not_found
from app.domain import models as m
from app.pipelines.measure import ensure_algorithm, measure_image
from app.services.common import location_dict, paginate, provenance
from fittrace.vision.gap import GapParams


def _list_item(img: m.InspectionImage, unit: m.ProductionUnit, loc: m.MeasurementLocation, run: m.InspectionRun | None,
               meas: m.Measurement | None) -> dict:
    return {"image_id": img.id, "serial": unit.serial, "unit_id": unit.id, "paint_code": unit.paint_code, "location": loc.code,
            "captured_at": img.captured_at, "run_status": run.status if run else None,
            "gap_mm": meas.gap_mm if meas else None, "deviation_mm": meas.deviation_mm if meas else None,
            "tolerance_status": meas.status if meas else None, "flags": list(run.flags) if run else []}


def list_inspections(db: Session, dataset: m.Dataset, location: str | None, status: str | None, q: str | None,
                     page: int, page_size: int, order: str = "desc") -> dict:
    offset, limit = paginate(page, page_size, get_settings().page_size_max)
    base = (select(m.InspectionImage, m.ProductionUnit, m.MeasurementLocation, m.InspectionRun, m.Measurement)
            .join(m.ProductionUnit, m.ProductionUnit.id == m.InspectionImage.unit_id)
            .join(m.MeasurementLocation, m.MeasurementLocation.id == m.InspectionImage.location_id)
            .outerjoin(m.InspectionRun, m.InspectionRun.id == m.InspectionImage.current_run_id)
            .outerjoin(m.Measurement, m.Measurement.run_id == m.InspectionRun.id)
            .where(m.InspectionImage.dataset_id == dataset.id))
    if location:
        base = base.where(m.MeasurementLocation.code == location)
    if status == "out_of_tolerance":
        base = base.where(m.Measurement.status.in_(["out_low", "out_high"]))
    elif status == "failed":
        base = base.where(m.InspectionRun.status == "failed")
    elif status:
        base = base.where(m.Measurement.status == status)
    if q:
        base = base.where(or_(m.ProductionUnit.serial.ilike(f"%{q.strip()}%")))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    ordering = m.InspectionImage.captured_at.desc() if order == "desc" else m.InspectionImage.captured_at.asc()
    rows = db.execute(base.order_by(ordering, m.InspectionImage.id).offset(offset).limit(limit)).all()
    return {"items": [_list_item(*r) for r in rows], "total": total, "page": page, "page_size": page_size}


def paint_out(db: Session, code: str | None) -> dict | None:
    if not code:
        return None
    p = db.get(m.PaintCode, code)
    return {"code": p.code, "name": p.name, "metallic": p.metallic} if p else None


def run_out(run: m.InspectionRun, current_id: int | None) -> dict:
    meas = run.measurement
    return {
        "id": run.id, "trigger": run.trigger, "status": run.status, "algorithm": run.algorithm.name,
        "algorithm_version": run.algorithm.version, "algorithm_params": run.algorithm.params,
        "failure_code": run.failure_code, "failure_message": run.failure_message, "duration_ms": run.duration_ms,
        "flags": run.flags or [], "diagnostics": run.diagnostics or {}, "overlay": run.overlay or {},
        "measurement": None if meas is None else {
            "gap_px": meas.gap_px, "gap_mm": meas.gap_mm, "std_error_mm": meas.std_error_mm,
            "deviation_mm": meas.deviation_mm, "angle_deg": meas.angle_deg, "calibrated": meas.calibrated,
            "status": meas.status},
        "created_at": run.created_at, "is_current": run.id == current_id,
    }


def get_inspection(db: Session, image_id: int) -> dict:
    img = db.get(m.InspectionImage, image_id)
    if img is None:
        raise not_found("inspection image", image_id)
    unit = db.get(m.ProductionUnit, img.unit_id)
    ds = db.get(m.Dataset, img.dataset_id)
    loc = db.get(m.MeasurementLocation, img.location_id)
    assert unit and ds and loc
    cal = db.get(m.CalibrationRecord, img.calibration_id) if img.calibration_id else None
    cam = db.get(m.Equipment, cal.camera_id) if cal else None
    runs = list(db.scalars(select(m.InspectionRun).where(m.InspectionRun.image_id == img.id)
                           .order_by(m.InspectionRun.created_at.desc(), m.InspectionRun.id.desc()).limit(20)))
    current = next((r for r in runs if r.id == img.current_run_id), None)
    if current is None and img.current_run_id:
        current = db.get(m.InspectionRun, img.current_run_id)
    inv_ids = list(db.scalars(select(m.QualityInvestigation.id).join(m.InspectionRun,
                   m.InspectionRun.id == m.QualityInvestigation.trigger_run_id).where(m.InspectionRun.image_id == img.id)))

    def neighbor(direction: str) -> int | None:
        q = (select(m.InspectionImage.id).where(m.InspectionImage.dataset_id == img.dataset_id,
                                                 m.InspectionImage.location_id == img.location_id))
        if direction == "prev":
            q = q.where(or_(m.InspectionImage.captured_at < img.captured_at,
                            (m.InspectionImage.captured_at == img.captured_at) & (m.InspectionImage.id < img.id)))
            q = q.order_by(m.InspectionImage.captured_at.desc(), m.InspectionImage.id.desc())
        else:
            q = q.where(or_(m.InspectionImage.captured_at > img.captured_at,
                            (m.InspectionImage.captured_at == img.captured_at) & (m.InspectionImage.id > img.id)))
            q = q.order_by(m.InspectionImage.captured_at.asc(), m.InspectionImage.id.asc())
        return db.scalar(q.limit(1))

    return {
        "image_id": img.id, "serial": unit.serial, "unit_id": unit.id, "dataset_key": ds.key,
        "paint": paint_out(db, unit.paint_code),
        "location": location_dict(db, loc), "captured_at": img.captured_at,
        "image_url": f"/api/v1/inspections/{img.id}/image", "width": img.width, "height": img.height,
        "sha256": img.sha256,
        "calibration": None if cal is None else {
            "reference": cal.reference, "camera": cam.code if cam else "?", "mm_per_px": cal.mm_per_px,
            "method": cal.method, "valid_from": cal.valid_from, "valid_to": cal.valid_to},
        "current_run": run_out(current, img.current_run_id) if current else None,
        "runs": [run_out(r, img.current_run_id) for r in runs],
        "provenance": provenance(ds),
        "investigation_ids": inv_ids,
        "neighbors": {"prev": neighbor("prev"), "next": neighbor("next")},
    }


def rerun(db: Session, image_id: int, overrides: dict) -> dict:
    img = db.get(m.InspectionImage, image_id)
    if img is None:
        raise not_found("inspection image", image_id)
    n_interactive = db.scalar(select(func.count()).select_from(m.InspectionRun)
                              .where(m.InspectionRun.image_id == image_id, m.InspectionRun.trigger == "interactive")) or 0
    if get_settings().demo_readonly and n_interactive >= 25:
        raise APIError(429, "rerun_limit", "interactive re-run limit reached for this image in the public demo")
    params = GapParams(**{**GapParams().to_dict(), **overrides})
    av = ensure_algorithm(db, params)
    run = measure_image(db, img, av, params, "interactive")
    db.commit()
    db.refresh(run)
    return run_out(run, img.current_run_id)


def ground_truth(db: Session, image_id: int) -> dict:
    img = db.get(m.InspectionImage, image_id)
    if img is None:
        raise not_found("inspection image", image_id)
    gt = db.get(m.GroundTruthGap, image_id)
    run = db.get(m.InspectionRun, img.current_run_id) if img.current_run_id else None
    meas = run.measurement if run else None
    if gt is None:
        return {"image_id": image_id, "available": False, "true_gap_mm": None, "measured_gap_mm": meas.gap_mm if meas else None,
                "error_um": None, "generator_version": None, "note": "no ground truth exists for this image"}
    err = (meas.gap_mm - gt.true_gap_mm) * 1000 if meas and meas.gap_mm is not None else None
    return {"image_id": image_id, "available": True, "true_gap_mm": gt.true_gap_mm,
            "measured_gap_mm": meas.gap_mm if meas else None, "error_um": err, "generator_version": gt.generator_version,
            "note": "Ground truth comes from the image generator and is never passed to the measurement algorithm."}
