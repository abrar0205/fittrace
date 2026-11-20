"""Contributor-recovery benchmark against injected simulated faults.

For each run a fresh plant history is simulated with one injected fault (or
none, for false-alarm estimation). Measured gaps are either

* ``mode="measurement_model"``: true gap + bias + N(0, sigma), with bias and
  sigma taken from the vision benchmark (fast; default), or
* ``mode="full_pipeline"``: every unit is rendered and measured by the vision
  algorithm (slow; used as a consistency check).

The investigation is evaluated at three horizons: the online CUSUM alarm, the
alarm plus 60 units, and the full history. Only data up to the horizon is used.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from fittrace.analytics.changepoint import cusum
from fittrace.analytics.investigation import investigate, shift_label
from fittrace.simulation.factory import LOCATIONS, MM_PER_PX, Fault, SimConfig, simulate
from fittrace.simulation.geometry import SceneParams, render_panel_gap
from fittrace.vision.gap import measure_gap

LOC = "FD-FF-M"
FAULT_CLASSES = [
    ("fixture_shift", ["FX-201", "FX-202", "FX-203"], (0.25, 0.55), "S20 side-aperture fixture shift"),
    ("tool_drift", ["NR-301", "NR-302"], (4.0, 8.0), "S30 nutrunner torque calibration drift"),
    ("fixture_shift", ["FX-101", "FX-102"], (0.30, 0.60), "S10 underbody fixture shift (weak coupling)"),
]
CUSUM_K, CUSUM_H, BASELINE = 0.5, 6.0, 60


def unit_frame(res, measured: dict[str, float]) -> pd.DataFrame:
    nominal = next(loc for loc in LOCATIONS if loc["code"] == LOC)["nominal_mm"]
    rows = []
    for u in res.units:
        r = {"serial": u.serial, "built_at": pd.Timestamp(u.built_at), "batch": u.batch,
             "shift": shift_label(pd.Timestamp(u.built_at)), "paint": u.paint, "deviation_mm": measured[u.serial] - nominal}
        for st in u.route:
            key = {"S10": "s10_fixture", "S20": "s20_fixture", "S30": "s30_tool", "S40": "s40_booth"}.get(st["station"])
            if key:
                r[key] = st["equipment"]
            for k, (v, _) in st["params"].items():
                if k != "cycle_time_s":
                    r[k] = v
        rows.append(r)
    return pd.DataFrame(rows)


def _measure(res, mode: str, bias: float, sigma: float, rng: np.random.Generator) -> dict[str, float]:
    out = {}
    for u in res.units:
        g = u.true_gaps[LOC]
        if mode == "full_pipeline":
            img, _ = render_panel_gap(SceneParams(gap_mm=g, mm_per_px=MM_PER_PX, **u.scene[LOC]))
            r = measure_gap(img, MM_PER_PX)
            out[u.serial] = r.gap_mm if r.ok else np.nan
        else:
            out[u.serial] = g + bias + rng.normal(0, sigma)
    return out


def _score(result: dict, target: str | None) -> dict:
    c = result.get("contributors")
    hyps = [h for h in (c["hypotheses"] if c else []) if h["status"] == "tested"]
    sig = [h for h in hyps if h["significant"]]
    rank_of = next((h["rank"] for h in hyps if h["level"] == target), None) if target else None
    target_sig = bool(target and any(h["level"] == target and h["significant"] for h in hyps))
    return {
        "shift_detected": result.get("conclusion") == "shift_detected",
        "n_significant": len(sig),
        "top1": bool(target_sig and rank_of == 1),
        "top3": bool(target_sig and rank_of is not None and rank_of <= 3),
        "rank_of_target": rank_of,
        "top_hypothesis": (hyps[0]["level"] or hyps[0]["factor"]) if hyps else None,
        "change_index": result.get("change_point", {}).get("index"),
    }


def run_investigation_benchmark(n_runs: int = 40, n_null: int | None = None, n_units: int = 400, seed: int = 5000,
                                mode: str = "measurement_model", meas_bias_mm: float = 0.0235,
                                meas_sigma_mm: float = 0.003, n_perm: int = 499) -> dict:
    n_null = n_runs // 4 if n_null is None else n_null
    rng = np.random.default_rng(seed)
    t0 = time.perf_counter()
    runs = []
    plan = [FAULT_CLASSES[i % len(FAULT_CLASSES)] for i in range(n_runs)] + [None] * n_null
    for i, fc in enumerate(plan):
        rs = int(rng.integers(0, 2**31 - 1))
        fault, label = None, "no fault (null)"
        if fc is not None:
            kind, targets, (lo, hi), label = fc
            fault = Fault(kind=kind, target=targets[int(rng.integers(len(targets)))],
                          start_index=int(rng.integers(int(n_units * 0.4), int(n_units * 0.65))),
                          magnitude=float(rng.uniform(lo, hi)), with_event=True)
        res = simulate(SimConfig(seed=rs, n_units=n_units, faults=[fault] if fault else []))
        meas = _measure(res, mode, meas_bias_mm, meas_sigma_mm, np.random.default_rng(rs + 1))
        df = unit_frame(res, meas).dropna(subset=["deviation_mm"]).reset_index(drop=True)
        y = df["deviation_mm"].to_numpy()
        base = y[:BASELINE]
        sig = float(np.mean(np.abs(np.diff(base))) / 1.128)
        cs = cusum(y, float(base.mean()), sig, CUSUM_K, CUSUM_H)
        alarm = cs["alarm_index"]
        alarm = alarm if (alarm is None or alarm >= BASELINE) else alarm
        record = {"run": i, "fault_class": label, "kind": fault.kind if fault else None,
                  "target": fault.target if fault else None, "start_index": fault.start_index if fault else None,
                  "magnitude": fault.magnitude if fault else None, "alarm_index": alarm,
                  "detection_delay": (alarm - fault.start_index) if (fault and alarm is not None) else None,
                  "alarm_before_fault": bool(fault and alarm is not None and alarm < fault.start_index)}
        events = res.equipment_events
        horizons = {"full_history": len(df)}
        if alarm is not None:
            horizons["at_alarm"] = alarm + 1
            horizons["alarm_plus_60"] = min(len(df), alarm + 61)
        for hname, hz in horizons.items():
            r = investigate(df.iloc[:hz], events=events, n_perm=n_perm, seed=rs)
            sc = _score(r, fault.target if fault else None)
            if fault and sc["change_index"] is not None:
                sc["cp_error_units"] = int(sc["change_index"] - fault.start_index)
            record[hname] = sc
        runs.append(record)

    def agg(sel: list[dict], horizon: str) -> dict:
        have = [r for r in sel if horizon in r]
        n = len(have)
        if not n:
            return {"n": 0}
        cp_err = [abs(r[horizon]["cp_error_units"]) for r in have if r[horizon].get("cp_error_units") is not None]
        return {
            "n": n,
            "top1_recovery": sum(r[horizon]["top1"] for r in have) / n,
            "top3_recovery": sum(r[horizon]["top3"] for r in have) / n,
            "shift_detected_rate": sum(r[horizon]["shift_detected"] for r in have) / n,
            "median_cp_error_units": float(np.median(cp_err)) if cp_err else None,
            "p90_cp_error_units": float(np.percentile(cp_err, 90)) if cp_err else None,
        }

    faulted = [r for r in runs if r["kind"]]
    nulls = [r for r in runs if not r["kind"]]
    classes = {}
    for fc in FAULT_CLASSES:
        sel = [r for r in faulted if r["fault_class"] == fc[3]]
        delays = [r["detection_delay"] for r in sel if r["detection_delay"] is not None and r["detection_delay"] >= 0]
        classes[fc[3]] = {
            "n": len(sel),
            "alarm_rate": sum(r["alarm_index"] is not None and not r["alarm_before_fault"] for r in sel) / max(1, len(sel)),
            "median_detection_delay_units": float(np.median(delays)) if delays else None,
            "horizons": {h: agg(sel, h) for h in ("at_alarm", "alarm_plus_60", "full_history")},
        }
    null_summary = {
        "n": len(nulls),
        "cusum_false_alarm_rate": sum(r["alarm_index"] is not None for r in nulls) / max(1, len(nulls)),
        "false_attribution_rate_full_history": sum(r["full_history"]["n_significant"] > 0 for r in nulls) / max(1, len(nulls)),
    }
    return {
        "mode": mode,
        "params": {"n_runs": n_runs, "n_null": n_null, "n_units": n_units, "seed": seed, "location": LOC,
                   "cusum": {"k": CUSUM_K, "h": CUSUM_H, "baseline": BASELINE}, "meas_bias_mm": meas_bias_mm,
                   "meas_sigma_mm": meas_sigma_mm, "n_perm": n_perm},
        "overall": {
            "faulted_runs": len(faulted),
            "top1_full_history": agg(faulted, "full_history").get("top1_recovery"),
            "top3_full_history": agg(faulted, "full_history").get("top3_recovery"),
            "top1_alarm_plus_60": agg(faulted, "alarm_plus_60").get("top1_recovery"),
            **{f"null_{k}": v for k, v in null_summary.items()},
        },
        "classes": classes,
        "null": null_summary,
        "runs": runs,
        "wall_time_s": round(time.perf_counter() - t0, 2),
    }
