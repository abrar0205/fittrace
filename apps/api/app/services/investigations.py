from __future__ import annotations

import math
import time

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import APIError, not_found
from app.domain import models as m
from app.repositories.sql import rows
from app.services.analytics import STATION_COLUMNS, _inv_list_item, series_rows
from app.services.common import location_dict, paginate, provenance
from fittrace.analytics.contributors import METHOD, METHOD_VERSION
from fittrace.analytics.investigation import investigate, shift_label


def _clean(o):
    """Make analysis output JSON-safe (no NaN/inf, numpy scalars to Python)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    return o


def build_frame(series: list[dict]) -> tuple[pd.DataFrame, int]:
    recs, incomplete = [], 0
    for r in series:
        if r["deviation_mm"] is None:
            continue
        route = r["route"] or {}
        if any(st not in route for st in STATION_COLUMNS):
            incomplete += 1
            continue
        rec = {"image_id": r["image_id"], "serial": r["serial"], "built_at": pd.Timestamp(r["built_at"]),
               "batch": r["batch_code"], "shift": shift_label(pd.Timestamp(r["built_at"])),
               "deviation_mm": float(r["deviation_mm"])}
        for st, col in STATION_COLUMNS.items():
            rec[col] = route[st]
        for k, v in (r["params"] or {}).items():
            rec[k] = float(v)
        recs.append(rec)
    return pd.DataFrame(recs), incomplete


def create_investigation(db: Session, image_id: int, baseline_n: int = 60, alpha: float = 0.05) -> m.QualityInvestigation:
    img = db.get(m.InspectionImage, image_id)
    if img is None:
        raise not_found("inspection image", image_id)
    if img.current_run_id is None:
        raise APIError(409, "not_measured", "this inspection has no measurement yet")
    run = db.get(m.InspectionRun, img.current_run_id)
    assert run is not None
    if run.status != "ok" or run.measurement is None:
        raise APIError(409, "measurement_failed", "the current measurement failed; there is no deviation to investigate",
                       {"failure_code": run.failure_code})
    if run.measurement.status not in ("out_low", "out_high"):
        raise APIError(409, "within_tolerance",
                       "investigations are triggered by out-of-tolerance inspections; this one is within tolerance")
    params = {"baseline_n": baseline_n, "alpha": alpha, "n_perm": 999, "seed": image_id}
    existing = db.scalar(select(m.QualityInvestigation).where(m.QualityInvestigation.trigger_run_id == run.id,
                                                               m.QualityInvestigation.method_version == METHOD_VERSION,
                                                               m.QualityInvestigation.params == params))
    if existing is not None:
        return existing
    ds = db.get(m.Dataset, img.dataset_id)
    unit = db.get(m.ProductionUnit, img.unit_id)
    loc = db.get(m.MeasurementLocation, img.location_id)
    assert ds and unit and loc
    t0 = time.perf_counter()
    series = series_rows(db, ds, loc.code, until=unit.built_at)
    df, incomplete = build_frame(series)
    events = [{"equipment": e.equipment_code, "occurred_at": e.occurred_at, "kind": e.kind, "description": e.description}
              for e in db.execute(select(m.Equipment.code.label("equipment_code"), m.EquipmentEvent.occurred_at,
                                         m.EquipmentEvent.kind, m.EquipmentEvent.description)
                                  .join(m.Equipment, m.Equipment.id == m.EquipmentEvent.equipment_id)
                                  .where(m.EquipmentEvent.dataset_id == ds.id,
                                         m.EquipmentEvent.occurred_at <= unit.built_at))]
    if len(df) < 40:
        raise APIError(409, "insufficient_history", f"only {len(df)} complete unit histories before this inspection")
    res = _clean(investigate(df, events=events, baseline_n=baseline_n, alpha=alpha, n_perm=999, seed=image_id))
    if incomplete:
        res["limitations"].insert(0, f"{incomplete} units were excluded because their route is incomplete "
                                     "(production events rejected during import).")
    contrib = res.get("contributors") or {}
    summary = {"n_units": res["n_units"], "excluded_incomplete": incomplete, "conclusion": res["conclusion"],
               "observed_shift_mm": contrib.get("observed_shift_mm"), "n_pre": contrib.get("n_pre"),
               "n_post": contrib.get("n_post"), "aliasing": contrib.get("aliasing", []), "cusum": res.get("cusum")}
    inv = m.QualityInvestigation(
        dataset_id=ds.id, trigger_run_id=run.id, location_id=loc.id, status=res["conclusion"], method=METHOD,
        method_version=METHOD_VERSION, params=params, change_point=res["change_point"], summary=summary,
        limitations=res["limitations"], duration_ms=round((time.perf_counter() - t0) * 1000, 2))
    db.add(inv)
    db.flush()
    for h in contrib.get("hypotheses", []):
        ci = h.get("ci95") or [None, None]
        db.add(m.ContributorHypothesis(
            investigation_id=inv.id, rank=h.get("rank"), factor_type=h["factor_type"], factor=h["factor"],
            level=h.get("level"), station_code=h.get("station"), status=h["status"], effect_mm=h.get("effect_mm"),
            ci_low=ci[0], ci_high=ci[1], p_value=h.get("p_value"), q_value=h.get("q_value"),
            attributable_shift_mm=h.get("attributable_shift_mm"), explained_fraction=h.get("explained_fraction"),
            significant=bool(h.get("significant")), n_pre=h.get("n_pre", 0), n_post=h.get("n_post", 0),
            reason=h.get("reason"), evidence=h.get("evidence") or {}))
    snapshot = {"image_id": df["image_id"].tolist(), "serial": df["serial"].tolist(),
                "built_at": [t.isoformat() for t in df["built_at"]], "deviation_mm": df["deviation_mm"].round(5).tolist(),
                **{col: df[col].tolist() for col in STATION_COLUMNS.values()}, "batch": df["batch"].tolist()}
    db.add(m.InvestigationEvidence(investigation_id=inv.id, kind="series_snapshot", payload=_clean(snapshot)))
    db.add(m.InvestigationEvidence(investigation_id=inv.id, kind="change_profile", payload=res.get("change_profile") or {}))
    db.commit()
    db.refresh(inv)
    return inv


def investigation_out(db: Session, inv: m.QualityInvestigation) -> dict:
    run = db.get(m.InspectionRun, inv.trigger_run_id)
    img = db.get(m.InspectionImage, run.image_id) if run else None
    unit = db.get(m.ProductionUnit, img.unit_id) if img else None
    ds = db.get(m.Dataset, inv.dataset_id)
    loc = db.get(m.MeasurementLocation, inv.location_id)
    assert run and img and unit and ds and loc
    meas = run.measurement
    ev = {e.kind: e.payload for e in inv.evidence}
    ver = rows(db, "intervention_comparison", investigation_id=inv.id)
    return {
        "id": inv.id, "status": inv.status, "method": inv.method, "method_version": inv.method_version,
        "created_at": inv.created_at, "duration_ms": inv.duration_ms,
        "trigger": {"image_id": img.id, "run_id": run.id, "serial": unit.serial, "unit_id": unit.id,
                    "built_at": unit.built_at.isoformat(), "gap_mm": meas.gap_mm if meas else None,
                    "deviation_mm": meas.deviation_mm if meas else None, "status": meas.status if meas else None},
        "location": location_dict(db, loc), "params": inv.params, "change_point": inv.change_point,
        "summary": inv.summary, "limitations": inv.limitations,
        "hypotheses": [{c: getattr(h, c) for c in ("rank", "factor_type", "factor", "level", "station_code", "status",
                                                    "effect_mm", "ci_low", "ci_high", "p_value", "q_value",
                                                    "attributable_shift_mm", "explained_fraction", "significant",
                                                    "n_pre", "n_post", "reason", "evidence")}
                       for h in sorted(inv.hypotheses, key=lambda h: (h.rank is None, h.rank or 0))],
        "evidence": ev, "provenance": provenance(ds), "verification_runs": ver,
    }


def get_investigation(db: Session, inv_id: int) -> dict:
    inv = db.get(m.QualityInvestigation, inv_id)
    if inv is None:
        raise not_found("investigation", inv_id)
    return investigation_out(db, inv)


def list_investigations(db: Session, page: int, page_size: int) -> dict:
    offset, limit = paginate(page, page_size, get_settings().page_size_max)
    total = db.scalar(select(func.count()).select_from(m.QualityInvestigation)) or 0
    newest_first = (m.QualityInvestigation.created_at.desc(), m.QualityInvestigation.id.desc())
    invs = db.scalars(select(m.QualityInvestigation).order_by(*newest_first)
                      .offset(offset).limit(limit))
    return {"items": [_inv_list_item(db, i) for i in invs], "total": total, "page": page, "page_size": page_size}
