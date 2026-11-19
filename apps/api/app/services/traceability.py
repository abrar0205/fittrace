from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import not_found
from app.domain import models as m
from app.repositories.sql import rows
from app.services.common import provenance
from app.services.inspections import _list_item


def unit_trace(db: Session, unit_id: int | None = None, serial: str | None = None, dataset_id: int | None = None,
               event_window_h: int = 48) -> dict:
    if unit_id is not None:
        unit = db.get(m.ProductionUnit, unit_id)
    else:
        q = select(m.ProductionUnit).where(m.ProductionUnit.serial == serial)
        if dataset_id is not None:
            q = q.where(m.ProductionUnit.dataset_id == dataset_id)
        unit = db.scalar(q.limit(1))
    if unit is None:
        raise not_found("production unit", unit_id if unit_id is not None else serial)
    ds = db.get(m.Dataset, unit.dataset_id)
    line = db.get(m.ProductionLine, unit.line_id)
    route = rows(db, "unit_route", unit_id=unit.id)
    insp = db.execute(
        select(m.InspectionImage, m.ProductionUnit, m.MeasurementLocation, m.InspectionRun, m.Measurement)
        .join(m.ProductionUnit, m.ProductionUnit.id == m.InspectionImage.unit_id)
        .join(m.MeasurementLocation, m.MeasurementLocation.id == m.InspectionImage.location_id)
        .outerjoin(m.InspectionRun, m.InspectionRun.id == m.InspectionImage.current_run_id)
        .outerjoin(m.Measurement, m.Measurement.run_id == m.InspectionRun.id)
        .where(m.InspectionImage.unit_id == unit.id).order_by(m.MeasurementLocation.code)).all()
    events = rows(db, "equipment_history_before", dataset_id=unit.dataset_id, unit_id=unit.id, built_at=unit.built_at,
                  hours=event_window_h)
    assert ds and line
    return {"unit_id": unit.id, "serial": unit.serial, "batch": unit.batch_code, "built_at": unit.built_at,
            "line": line.code, "dataset_key": ds.key, "route": route, "inspections": [_list_item(*r) for r in insp],
            "equipment_events": events, "provenance": provenance(ds)}
