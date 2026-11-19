"""Simulated corrective-action verification.

The plant simulator continues production after the last imported unit twice,
with identical random draws: once unchanged (counterfactual baseline) and once
with the selected corrective action applied. Both scenarios are rendered and
measured by the same vision algorithm. Because the draws are identical, the
comparison is paired and isolates the effect of the action *within the
simulation*. It demonstrates a verification workflow; it is not evidence about
any real process.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
from scipy import stats
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import APIError, not_found
from app.domain import models as m
from app.services import jobs
from app.services.common import location_dict
from fittrace.simulation.factory import EQUIPMENT, MM_PER_PX, Fault, SimConfig, simulate
from fittrace.simulation.geometry import SceneParams, render_panel_gap
from fittrace.vision.gap import GapParams, measure_gap
from fittrace.vision.tolerance import ToleranceSpec

EQUIPMENT_BY_CODE = {e["code"]: e for e in EQUIPMENT}


def create_verification(db: Session, investigation_id: int, target_code: str, kind: str, n_units: int, seed: int) -> dict:
    inv = db.get(m.QualityInvestigation, investigation_id)
    if inv is None:
        raise not_found("investigation", investigation_id)
    if target_code not in EQUIPMENT_BY_CODE or EQUIPMENT_BY_CODE[target_code]["kind"] == "camera":
        raise APIError(422, "validation_error", f"{target_code!r} is not a fixture or tool of the simulated line")
    eq_kind = EQUIPMENT_BY_CODE[target_code]["kind"]
    if (kind == "realign_fixture") != (eq_kind == "fixture"):
        raise APIError(422, "validation_error", f"{kind} does not apply to a {eq_kind}")
    n_units = min(n_units, get_settings().max_verification_units)
    desc = (f"Simulated {'re-alignment of fixture' if eq_kind == 'fixture' else 're-calibration of tool'} {target_code}: "
            "the simulator removes any injected fault on this resource from the next unit onward.")
    ca = m.CorrectiveAction(investigation_id=inv.id, kind=kind, target_code=target_code, description=desc)
    db.add(ca)
    db.flush()
    job = jobs.enqueue(db, "verify_corrective_action", {"corrective_action_id": ca.id})
    vr = m.VerificationRun(corrective_action_id=ca.id, job_id=job.id, status="queued", n_units=n_units, seed=seed, result={})
    db.add(vr)
    db.flush()
    job.payload = {"verification_run_id": vr.id}
    db.commit()
    return verification_out(db, vr)


def verification_out(db: Session, vr: m.VerificationRun) -> dict:
    ca = db.get(m.CorrectiveAction, vr.corrective_action_id)
    job = db.get(m.Job, vr.job_id) if vr.job_id else None
    assert ca
    return {"id": vr.id, "status": vr.status, "n_units": vr.n_units, "seed": vr.seed, "target_code": ca.target_code,
            "kind": ca.kind, "investigation_id": ca.investigation_id, "result": vr.result or {},
            "created_at": vr.created_at, "finished_at": vr.finished_at,
            "job": None if job is None else {c: getattr(job, c) for c in (
                "id", "kind", "status", "progress", "message", "error", "attempts", "max_attempts", "result",
                "created_at", "started_at", "finished_at")}}


def get_verification(db: Session, vr_id: int) -> dict:
    vr = db.get(m.VerificationRun, vr_id)
    if vr is None:
        raise not_found("verification run", vr_id)
    return verification_out(db, vr)


def _summ(gaps: np.ndarray, spec: ToleranceSpec) -> dict:
    ok = gaps[np.isfinite(gaps)]
    oot = int(np.sum((ok < spec.lsl) | (ok > spec.usl)))
    return {"n": int(len(ok)), "mean_mm": float(ok.mean()), "sd_mm": float(ok.std(ddof=1)), "n_oot": oot,
            "oot_rate": oot / max(1, len(ok)), "failed_measurements": int(np.sum(~np.isfinite(gaps)))}


def execute_verification(vr_id: int, progress) -> dict:
    SessionLocal = get_sessionmaker()
    with SessionLocal() as db, db.begin():
        vr = db.get(m.VerificationRun, vr_id)
        if vr is None:
            raise LookupError(f"verification run {vr_id} not found")
        vr.status = "running"
        ca = db.get(m.CorrectiveAction, vr.corrective_action_id)
        inv = db.get(m.QualityInvestigation, ca.investigation_id)
        loc = db.get(m.MeasurementLocation, inv.location_id)
        locd = location_dict(db, loc)
        faults = [Fault(kind=f.kind, target=f.target_code, start_index=f.start_index, magnitude=f.magnitude, with_event=False)
                  for f in db.scalars(select(m.FaultInjection).where(m.FaultInjection.dataset_id == inv.dataset_id))]
        n_existing = db.scalar(select(func.count()).select_from(m.ProductionUnit)
                               .where(m.ProductionUnit.dataset_id == inv.dataset_id)) or 0
        last_built = db.scalar(select(func.max(m.ProductionUnit.built_at)).where(m.ProductionUnit.dataset_id == inv.dataset_id))
        n_units, seed, target, loc_code = vr.n_units, vr.seed, ca.target_code, loc.code
    spec = ToleranceSpec(locd["nominal_mm"], locd["lower_tol_mm"], locd["upper_tol_mm"])
    common = {"seed": 900_000 + seed, "n_units": n_units, "start": last_built, "faults": faults,
              "serial_offset": n_existing, "serial_prefix": "VER"}
    base = simulate(SimConfig(**common))
    adj = simulate(SimConfig(**common, realigned=(target,)))
    station = EQUIPMENT_BY_CODE[target]["station"]
    gp = GapParams()
    out = {"baseline": [], "adjusted": []}
    total = 2 * n_units
    for si, (name, res) in enumerate((("baseline", base), ("adjusted", adj))):
        for i, u in enumerate(res.units):
            img, _ = render_panel_gap(SceneParams(gap_mm=u.true_gaps[loc_code], mm_per_px=MM_PER_PX, **u.scene[loc_code]))
            r = measure_gap(img, MM_PER_PX, gp)
            eq = next(s["equipment"] for s in u.route if s["station"] == station)
            out[name].append({"serial": u.serial, "gap_mm": r.gap_mm if r.ok else None, "equipment": eq,
                              "failure_code": r.failure_code})
            if i % 20 == 0:
                progress((si * n_units + i) / total, f"{name}: measured {i}/{n_units} simulated units")
    b = np.array([x["gap_mm"] if x["gap_mm"] is not None else np.nan for x in out["baseline"]])
    a = np.array([x["gap_mm"] if x["gap_mm"] is not None else np.nan for x in out["adjusted"]])
    both = np.isfinite(a) & np.isfinite(b)
    d = a[both] - b[both]
    tcrit = float(stats.t.ppf(0.975, max(1, len(d) - 1)))
    sb, sa = _summ(b, spec), _summ(a, spec)
    pooled = np.sqrt((np.nanvar(a, ddof=1) + np.nanvar(b, ddof=1)) / 2)
    g = float((np.nanmean(a) - np.nanmean(b)) / pooled) if pooled > 0 else None
    fisher = stats.fisher_exact([[sb["n_oot"], sb["n"] - sb["n_oot"]], [sa["n_oot"], sa["n"] - sa["n_oot"]]])
    on_target = [i for i, x in enumerate(out["baseline"]) if x["equipment"] == target]
    tgt = None
    if on_target:
        idx = np.array(on_target)
        tb, ta = b[idx], a[idx]
        tgt = {"n": len(idx), "baseline_mean_mm": float(np.nanmean(tb)), "adjusted_mean_mm": float(np.nanmean(ta)),
               "mean_change_mm": float(np.nanmean(ta - tb))}
    result = {
        "simulated": True,
        "statement": "Simulated experiment: both scenarios come from the plant simulator, measured by the vision algorithm.",
        "location": loc_code, "target_code": target, "station": station,
        "spec": {"nominal_mm": spec.nominal_mm, "lsl": spec.lsl, "usl": spec.usl},
        "baseline": sb, "adjusted": sa,
        "paired_mean_change_mm": float(d.mean()) if len(d) else None,
        "paired_ci95_mm": [float(d.mean() - tcrit * d.std(ddof=1) / np.sqrt(len(d))),
                           float(d.mean() + tcrit * d.std(ddof=1) / np.sqrt(len(d)))] if len(d) > 1 else None,
        "hedges_g": g,
        "oot_rate_change": sa["oot_rate"] - sb["oot_rate"],
        "fisher_p": float(fisher.pvalue),
        "on_target_equipment": tgt,
        "simulation": {"seed": common["seed"], "n_units": n_units, "serial_offset": n_existing,
                       "faults_active_in_plant": [f.__dict__ for f in faults], "realigned": [target]},
        "units": {"baseline": out["baseline"], "adjusted": out["adjusted"]},
    }
    with SessionLocal() as db, db.begin():
        vr = db.get(m.VerificationRun, vr_id)
        vr.status, vr.result, vr.finished_at = "succeeded", result, datetime.now(UTC)
    return {"verification_run_id": vr_id, "paired_mean_change_mm": result["paired_mean_change_mm"]}


def mark_failed(vr_id: int, error: str) -> None:
    with get_sessionmaker()() as db, db.begin():
        vr = db.get(m.VerificationRun, vr_id)
        if vr:
            vr.status = "failed"
            vr.result = {"error": error}
