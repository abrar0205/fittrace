from __future__ import annotations

import math

import numpy as np
from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import APIError
from app.domain import models as m
from app.repositories.sql import rows
from app.services.common import dataset_out, location_dict, location_out, provenance
from fittrace.analytics.spc import capability, imr_chart

STATION_COLUMNS = {"S10": "s10_fixture", "S20": "s20_fixture", "S30": "s30_tool"}


def series_rows(db: Session, ds: m.Dataset, location: str, until=None) -> list[dict]:
    return rows(db, "measurement_series", dataset_id=ds.id, location=location, until=until)


def series(db: Session, ds: m.Dataset, location: str) -> dict:
    loc = location_out(db, location)
    rs = series_rows(db, ds, location)
    pts = [{"image_id": r["image_id"], "serial": r["serial"], "built_at": r["built_at"], "gap_mm": r["gap_mm"],
            "deviation_mm": r["deviation_mm"], "tolerance_status": r["tolerance_status"], "route": r["route"] or {},
            "batch": r["batch_code"]} for r in rs if r["gap_mm"] is not None]
    return {"location": loc, "points": pts, "failed_runs": sum(1 for r in rs if r["run_status"] == "failed"),
            "provenance": provenance(ds)}


def spc(db: Session, ds: m.Dataset, location: str, baseline_n: int) -> dict:
    loc = location_out(db, location)
    rs = [r for r in series_rows(db, ds, location) if r["gap_mm"] is not None]
    if len(rs) < 2:
        raise APIError(409, "insufficient_data", "fewer than two measured inspections for this location")
    x = np.array([r["gap_mm"] for r in rs])
    ch = imr_chart(x, baseline_n)
    signals = []
    for i in range(len(x)):
        s = [name for name, key in (("R1", "rule1"), ("R2", "rule2"), ("R4", "rule4"), ("MR", "mr_out")) if ch[key][i]]
        signals.append(s)
    base_flagged = [i for i in range(ch["baseline_n"]) if signals[i]]
    rules = sorted({r for i in base_flagged for r in signals[i]})
    if not ch["applicable"]:
        cap, note = None, "Capability is not reported: the chart is not applicable to this baseline."
    else:
        cap, note = None, (f"Capability is not reported: {len(base_flagged)} baseline points carry signals ({', '.join(rules)}), "
                           "so the baseline is not demonstrably stable.")
    if ch["applicable"] and not base_flagged:
        cap = capability(x[: ch["baseline_n"]], loc["lsl_mm"], loc["usl_mm"], ch["sigma_hat"])
        note = (f"Cp/Cpk computed from the first {ch['baseline_n']} units (in-control baseline) with within-process "
                "sigma (MR-bar/d2). Not valid for later periods if they show signals.")
    return {"location": loc, "applicable": ch["applicable"], "n": ch["n"], "baseline_n": ch["baseline_n"],
            "center": ch["center"], "sigma_hat": ch["sigma_hat"], "ucl": ch["ucl"], "lcl": ch["lcl"],
            "mr_bar": ch["mr_bar"], "mr_ucl": ch["mr_ucl"], "values": x.tolist(), "moving_range": ch["moving_range"],
            "image_ids": [r["image_id"] for r in rs], "serials": [r["serial"] for r in rs],
            "built_at": [r["built_at"] for r in rs], "signals": signals, "first_signal_index": ch["first_signal_index"],
            "warnings": ch["warnings"], "capability": cap, "capability_note": note}


def station_comparison(db: Session, ds: m.Dataset, location: str, station: str) -> dict:
    loc = location_out(db, location)
    if station not in STATION_COLUMNS:
        raise APIError(422, "validation_error", f"station must be one of {sorted(STATION_COLUMNS)}")
    groups = []
    for r in rows(db, "station_distribution", dataset_id=ds.id, location=location, station=station):
        vals = [v for v in r["values"] if v is not None]
        groups.append({"equipment": r["equipment"], "n": r["n"], "mean_mm": r["mean_mm"], "sd_mm": r["sd_mm"],
                       "median_mm": r["median_mm"], "p05_mm": r["p05_mm"], "p95_mm": r["p95_mm"], "n_oot": r["n_oot"],
                       "oot_rate": r["n_oot"] / r["n"] if r["n"] else 0.0, "values": vals})
    samples = [g["values"] for g in groups if len(g["values"]) >= 3]
    anova_p = kruskal_p = None
    if len(samples) >= 2:
        anova_p = float(stats.f_oneway(*samples).pvalue)
        kruskal_p = float(stats.kruskal(*samples).pvalue)
    note = ("Group differences over the whole period. A difference that only exists after a certain time is better "
            "examined in an investigation, which compares groups before and after a detected change point.")
    return {"location": loc, "station": station, "groups": groups,
            "anova_p": anova_p if anova_p is None or math.isfinite(anova_p) else None,
            "kruskal_p": kruskal_p, "note": note}


def overview(db: Session, ds: m.Dataset | None) -> dict:
    datasets = [dataset_out(db, d) for d in db.scalars(select(m.Dataset).order_by(m.Dataset.id))]
    pipelines = rows(db, "pipeline_health")
    if ds is None:
        return {"dataset": None, "locations": [], "latest_oot": [], "trend": [], "recent_investigations": [],
                "pipelines": pipelines, "datasets": datasets, "provenance": None}
    trend = rows(db, "deviation_trend", dataset_id=ds.id)
    locs = []
    for loc in db.scalars(select(m.MeasurementLocation).order_by(m.MeasurementLocation.code)):
        rs = [r for r in series_rows(db, ds, loc.code)]
        meas = [r for r in rs if r["gap_mm"] is not None]
        vals = np.array([r["gap_mm"] for r in meas]) if meas else np.array([])
        hist = None
        ld = location_dict(db, loc)
        if len(vals):
            lo, hi = min(vals.min(), ld["lsl_mm"] - 0.1), max(vals.max(), ld["usl_mm"] + 0.1)
            counts, edges = np.histogram(vals, bins=40, range=(lo, hi))
            hist = {"counts": counts.tolist(), "edges": edges.tolist()}
        locs.append({**ld, "inspections": len(rs), "measured": len(meas),
                     "failed": sum(1 for r in rs if r["run_status"] == "failed"),
                     "out_of_tolerance": sum(1 for r in meas if r["tolerance_status"] in ("out_low", "out_high")),
                     "mean_mm": float(vals.mean()) if len(vals) else None,
                     "sd_mm": float(vals.std(ddof=1)) if len(vals) > 1 else None, "histogram": hist,
                     "sparkline": [round(float(v), 4) for v in vals[-120:]]})
    invs = []
    for inv in db.scalars(select(m.QualityInvestigation).where(m.QualityInvestigation.dataset_id == ds.id)
                          .order_by(m.QualityInvestigation.created_at.desc(), m.QualityInvestigation.id.desc()).limit(6)):
        invs.append(_inv_list_item(db, inv))
    return {"dataset": dataset_out(db, ds), "locations": locs,
            "latest_oot": rows(db, "latest_out_of_tolerance", dataset_id=ds.id, limit=8), "trend": trend,
            "recent_investigations": invs, "pipelines": pipelines, "datasets": datasets, "provenance": provenance(ds)}


def _inv_list_item(db: Session, inv: m.QualityInvestigation) -> dict:
    run = db.get(m.InspectionRun, inv.trigger_run_id)
    img = db.get(m.InspectionImage, run.image_id) if run else None
    unit = db.get(m.ProductionUnit, img.unit_id) if img else None
    loc = db.get(m.MeasurementLocation, inv.location_id)
    top = next((h for h in inv.hypotheses if h.rank == 1), None)
    return {"id": inv.id, "status": inv.status, "created_at": inv.created_at, "serial": unit.serial if unit else "?",
            "location": loc.code if loc else "?", "image_id": img.id if img else 0,
            "top_hypothesis": (f"{top.factor} = {top.level}" if top and top.level else (top.factor if top else None)),
            "top_explained_fraction": top.explained_fraction if top and top.significant else None}
