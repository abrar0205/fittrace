"""Gap-measurement benchmark against generated ground truth.

Each *condition* sweeps one nuisance parameter while the others are drawn from
the nominal operating distribution. For every sample the algorithm receives
only the rendered image and the (possibly mis-specified) calibration scale.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace

import numpy as np

from fittrace.simulation.geometry import GENERATOR_VERSION, SceneParams, render_panel_gap
from fittrace.vision.gap import ALGORITHM_NAME, ALGORITHM_VERSION, GapParams, measure_gap
from fittrace.vision.tolerance import ToleranceSpec

SPEC = ToleranceSpec(4.0, -0.5, 0.5)

CONDITIONS: dict[str, dict] = {
    "noise_sigma": {"label": "Sensor noise (fraction of full scale)", "values": [0.005, 0.015, 0.03, 0.06, 0.1, 0.15]},
    "angle_deg": {"label": "Edge rotation (deg)", "values": [0, 2, 4, 6, 8, 12]},
    "illumination_gradient": {"label": "Illumination gradient across field", "values": [0, 0.2, 0.4, 0.6, 0.8]},
    "gap_mm": {"label": "Gap width (mm)", "values": [0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 4.0, 6.0, 8.0]},
    "edge_rolloff_mm": {"label": "Edge roll-off / hem shading (mm)", "values": [0, 0.03, 0.06, 0.1, 0.2]},
    "edge_blur_px": {"label": "Optical blur sigma (px)", "values": [0.5, 1.0, 2.0, 3.0, 5.0]},
    "occlusion_fraction": {"label": "Occluded fraction of rows (partial visibility)", "values": [0, 0.2, 0.4, 0.6, 0.7, 0.8]},
    "calibration_error_pct": {"label": "Calibration scale error (%)", "values": [-2, -1, 0, 1, 2]},
    "mm_per_px": {"label": "Camera resolution (mm/px)", "values": [0.01, 0.02, 0.025, 0.04, 0.06]},
}


def nominal_scene(rng: np.random.Generator, seed: int) -> SceneParams:
    return SceneParams(
        gap_mm=float(rng.uniform(3.0, 5.0)),
        angle_deg=float(rng.normal(0, 1.0)),
        center_offset_mm=float(rng.uniform(-0.8, 0.8)),
        illumination_gradient=float(rng.normal(0, 0.12)),
        noise_sigma=float(abs(rng.normal(0.016, 0.004))),
        edge_rolloff_mm=float(abs(rng.normal(0.06, 0.01))),
        left_level=float(rng.uniform(0.72, 0.82)),
        right_level=float(rng.uniform(0.70, 0.80)),
        seed=seed,
    )


def _sample(args: tuple[str, float, int]) -> dict:
    cond, value, seed = args
    rng = np.random.default_rng(seed)
    p = nominal_scene(rng, seed)
    assumed_scale = p.mm_per_px
    if cond == "nominal":
        pass
    elif cond == "calibration_error_pct":
        assumed_scale = p.mm_per_px * (1 + value / 100.0)
    elif cond == "gap_mm":
        p = replace(p, gap_mm=float(value), center_offset_mm=float(rng.uniform(-0.3, 0.3)))
    elif cond == "mm_per_px":
        p = replace(p, mm_per_px=float(value))
        assumed_scale = float(value)
    else:
        p = replace(p, **{cond: float(value)})
    img, gt = render_panel_gap(p)
    t0 = time.perf_counter()
    r = measure_gap(img, assumed_scale, GapParams())
    latency = (time.perf_counter() - t0) * 1000
    true_status, _ = SPEC.evaluate(gt.gap_mm)
    pred_status = SPEC.evaluate(r.gap_mm)[0] if r.ok else None
    return {
        "condition": cond, "value": value, "seed": seed, "ok": r.ok, "failure_code": r.failure_code,
        "true_gap_mm": gt.gap_mm, "gap_mm": r.gap_mm, "error_mm": (r.gap_mm - gt.gap_mm) if r.ok else None,
        "true_oot": true_status.value != "in_tolerance", "pred_oot": (pred_status.value != "in_tolerance") if pred_status else None,
        "latency_ms": latency, "flags": r.flags, "scene": p.to_dict(), "assumed_mm_per_px": assumed_scale,
    }


def _metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["ok"]]
    e = np.array([r["error_mm"] for r in ok], dtype=float)
    lat = np.array([r["latency_ms"] for r in rows], dtype=float)
    cls = [r for r in ok]
    tp = sum(1 for r in cls if r["true_oot"] and r["pred_oot"])
    tn = sum(1 for r in cls if not r["true_oot"] and not r["pred_oot"])
    fp = sum(1 for r in cls if not r["true_oot"] and r["pred_oot"])
    fn = sum(1 for r in cls if r["true_oot"] and not r["pred_oot"])

    def f(x):
        return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else float(x)

    return {
        "n": len(rows),
        "n_ok": len(ok),
        "failure_rate": 1 - len(ok) / max(1, len(rows)),
        "mae_um": f(np.mean(np.abs(e)) * 1000) if len(e) else None,
        "rmse_um": f(np.sqrt(np.mean(e**2)) * 1000) if len(e) else None,
        "bias_um": f(np.mean(e) * 1000) if len(e) else None,
        "p95_abs_um": f(np.percentile(np.abs(e), 95) * 1000) if len(e) else None,
        "classification_accuracy": f((tp + tn) / len(cls)) if cls else None,
        "false_positive_rate": f(fp / (fp + tn)) if (fp + tn) else None,
        "false_negative_rate": f(fn / (fn + tp)) if (fn + tp) else None,
        "latency_p50_ms": f(np.percentile(lat, 50)) if len(lat) else None,
        "latency_p95_ms": f(np.percentile(lat, 95)) if len(lat) else None,
        "failure_codes": {c: sum(1 for r in rows if r["failure_code"] == c) for c in {r["failure_code"] for r in rows} if c},
    }


def run_vision_benchmark(per_condition: int = 24, nominal_n: int = 200, seed: int = 1000, workers: int = 4) -> dict:
    jobs: list[tuple[str, float, int]] = [("nominal", 0.0, seed + i) for i in range(nominal_n)]
    s = seed + 10_000
    for cond, spec in CONDITIONS.items():
        for v in spec["values"]:
            for _ in range(per_condition):
                jobs.append((cond, float(v), s))
                s += 1
    t0 = time.perf_counter()
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(_sample_safe, jobs, chunksize=8))
    else:
        rows = [_sample_safe(j) for j in jobs]
    nominal = [r for r in rows if r["condition"] == "nominal"]
    out_conditions = {}
    for cond, spec in CONDITIONS.items():
        points = []
        for v in spec["values"]:
            sub = [r for r in rows if r["condition"] == cond and r["value"] == float(v)]
            points.append({"value": v, **_metrics(sub)})
        out_conditions[cond] = {"label": spec["label"], "points": points}
    failures = [r for r in rows if not r["ok"]]
    # Worst cases exclude the deliberately mis-calibrated condition, whose error is known by construction.
    worst = sorted((r for r in rows if r["ok"] and r["condition"] != "calibration_error_pct"),
                   key=lambda r: -abs(r["error_mm"]))[:6]
    by_kind: dict = {}
    for r in failures:  # one example per (condition, value, failure code)
        by_kind.setdefault((r["condition"], r["value"], r["failure_code"]), r)
    cases = [{"kind": "failure", **_case(r)} for r in list(by_kind.values())[:6]]
    cases += [{"kind": "largest_error", **_case(r)} for r in worst]
    return {
        "algorithm": f"{ALGORITHM_NAME}@{ALGORITHM_VERSION}",
        "generator": GENERATOR_VERSION,
        "spec": {"nominal_mm": SPEC.nominal_mm, "lsl": SPEC.lsl, "usl": SPEC.usl},
        "params": {"per_condition": per_condition, "nominal_n": nominal_n, "seed": seed},
        "overall": {"condition": "nominal operating distribution", **_metrics(nominal)},
        "nominal_errors_um": [round(r["error_mm"] * 1000, 3) for r in nominal if r["ok"]],
        "conditions": out_conditions,
        "cases": cases,
        "wall_time_s": round(time.perf_counter() - t0, 2),
    }


def _sample_safe(args):
    try:
        return _sample(args)
    except Exception as e:  # noqa: BLE001 - a crash is a benchmark finding, not a benchmark failure
        return {"condition": args[0], "value": args[1], "seed": args[2], "ok": False, "failure_code": f"exception:{type(e).__name__}",
                "true_gap_mm": None, "gap_mm": None, "error_mm": None, "true_oot": False, "pred_oot": None,
                "latency_ms": 0.0, "flags": [], "scene": {}, "assumed_mm_per_px": None}


def _case(r: dict) -> dict:
    return {k: r[k] for k in ("condition", "value", "seed", "ok", "failure_code", "true_gap_mm", "gap_mm", "error_mm",
                              "flags", "scene", "assumed_mm_per_px")}
