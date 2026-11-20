from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import APIError, not_found
from app.domain import models as m


def resolve_dataset(db: Session, key: str | None) -> m.Dataset:
    if key:
        ds = db.scalar(select(m.Dataset).where(m.Dataset.key == key))
        if ds is None:
            raise not_found("dataset", key)
        return ds
    ds = db.scalar(select(m.Dataset).where(m.Dataset.kind == "synthetic").order_by(m.Dataset.id).limit(1))
    if ds is None:
        raise APIError(404, "no_data", "no dataset has been imported yet; run `python -m app.cli seed-demo`")
    return ds


def provenance(ds: m.Dataset) -> dict:
    simulated = ds.kind == "synthetic"
    return {
        "dataset_key": ds.key,
        "dataset_kind": ds.kind,
        "simulated": simulated,
        "statement": (
            "Simulated production history and procedurally generated, calibrated inspection images. "
            "Not real factory data; no affiliation with any manufacturer."
            if simulated else ds.provenance
        ),
    }


def location_out(db: Session, code: str) -> dict:
    loc = db.scalar(select(m.MeasurementLocation).where(m.MeasurementLocation.code == code))
    if loc is None:
        raise not_found("measurement location", code)
    return location_dict(db, loc)


def location_dict(db: Session, loc: m.MeasurementLocation) -> dict:
    spec = db.scalar(select(m.ToleranceSpecification).where(m.ToleranceSpecification.location_id == loc.id)
                     .order_by(m.ToleranceSpecification.version.desc()).limit(1))
    if spec is None:
        raise APIError(409, "missing_specification", f"location {loc.code} has no tolerance specification")
    return {"code": loc.code, "name": loc.name, "description": loc.description, "nominal_mm": spec.nominal_mm,
            "lower_tol_mm": spec.lower_tol_mm, "upper_tol_mm": spec.upper_tol_mm,
            "lsl_mm": spec.nominal_mm + spec.lower_tol_mm, "usl_mm": spec.nominal_mm + spec.upper_tol_mm}


def dataset_out(db: Session, ds: m.Dataset) -> dict:
    units = db.scalar(select(func.count()).select_from(m.ProductionUnit).where(m.ProductionUnit.dataset_id == ds.id)) or 0
    images = db.scalar(select(func.count()).select_from(m.InspectionImage).where(m.InspectionImage.dataset_id == ds.id)) or 0
    measured = db.scalar(select(func.count()).select_from(m.InspectionImage)
                         .where(m.InspectionImage.dataset_id == ds.id, m.InspectionImage.current_run_id.is_not(None))) or 0
    return {"id": ds.id, "key": ds.key, "name": ds.name, "kind": ds.kind, "provenance": ds.provenance,
            "license": ds.license, "created_at": ds.created_at, "units": units, "images": images, "measured": measured}


def paginate(page: int, page_size: int, max_size: int) -> tuple[int, int]:
    if page < 1:
        raise APIError(422, "validation_error", "page must be >= 1")
    if not 1 <= page_size <= max_size:
        raise APIError(422, "validation_error", f"page_size must be between 1 and {max_size}")
    return (page - 1) * page_size, page_size
