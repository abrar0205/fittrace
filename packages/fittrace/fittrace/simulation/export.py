"""Write a simulation run as a raw, MES-style export directory.

The export is what the ETL pipeline ingests. It deliberately contains a small,
documented rate of data-quality defects (missing values, malformed numbers,
out-of-range readings, unknown codes, orphans and exact duplicates) so that the
validation and rejection paths are exercised by real data. Every injected
defect is counted in ``manifest.json``.

Ground truth (true gaps, injected faults) is written to separate files and is
loaded into separate tables. The measurement algorithm never reads them.
"""

from __future__ import annotations

import csv
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from fittrace.simulation.appearance import PAINTS
from fittrace.simulation.factory import EQUIPMENT, LINE, LOCATIONS, MM_PER_PX, STATIONS, SimResult
from fittrace.simulation.geometry import GENERATOR_VERSION, SceneParams, encode_png, render_panel_gap

EXPORT_FORMAT = "fittrace-mes-export/1"


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _render_job(args: tuple[str, dict]) -> tuple[str, bytes, dict]:
    path, scene = args
    img, gt = render_panel_gap(SceneParams(**scene))
    return path, encode_png(img), {"true_gap_mm": gt.gap_mm, "true_gap_px": gt.gap_px}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def write_export(
    res: SimResult,
    out_dir: str | Path,
    dataset_key: str,
    dq_defect_rate: float = 0.01,
    dq_seed: int = 7,
    workers: int = 4,
    render: bool = True,
    unit_range: tuple[int, int] | None = None,
) -> dict:
    """Write ``res`` (optionally only units ``unit_range=(start, stop)``) as an export.

    A unit range lets one continuous simulation be delivered as successive
    increments, like a real MES export schedule; equipment events are split by
    the time window of the selected units.
    """
    if unit_range is not None:
        sel = res.units[unit_range[0] : unit_range[1]]
        lo = sel[0].built_at if unit_range[0] > 0 else datetime.min.replace(tzinfo=UTC)
        hi = res.units[unit_range[1]].built_at if unit_range[1] < len(res.units) else datetime.max.replace(tzinfo=UTC)
        res = SimResult(config=res.config, units=sel,
                        equipment_events=[e for e in res.equipment_events if lo <= e["occurred_at"] < hi],
                        simulator_version=res.simulator_version)
    out = Path(out_dir)
    (out / "images").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(dq_seed)
    injected = {"missing_value": 0, "malformed_number": 0, "out_of_range": 0, "unknown_code": 0,
                "orphan_reference": 0, "exact_duplicate": 0}

    def maybe_defect(row: dict, numeric_field: str | None, code_field: str | None, time_field: str | None,
                     ref_field: str | None) -> list[dict]:
        rows = [row]
        if rng.random() >= dq_defect_rate:
            return rows
        options = ["exact_duplicate"]
        if time_field:
            options.append("missing_value")
        if numeric_field:
            options += ["malformed_number", "out_of_range"]
        if code_field:
            options.append("unknown_code")
        if ref_field:
            options.append("orphan_reference")
        kind = options[int(rng.integers(len(options)))]
        bad = dict(row)
        if kind == "exact_duplicate":
            rows.append(dict(row))
        elif kind == "missing_value":
            bad[time_field] = ""  # type: ignore[index]
            rows = [bad]
        elif kind == "malformed_number":
            bad[numeric_field] = str(bad[numeric_field]).replace(".", ",") + "x"  # type: ignore[index]
            rows = [bad]
        elif kind == "out_of_range":
            bad[numeric_field] = "-999"  # type: ignore[index]
            rows = [bad]
        elif kind == "unknown_code":
            bad[code_field] = "S99"  # type: ignore[index]
            rows = [bad]
        elif kind == "orphan_reference":
            bad[ref_field] = "SIM-99999"  # type: ignore[index]
            rows = [bad]
        injected[kind] += 1
        return rows

    def write_csv(name: str, header: list[str], rows: list[dict]) -> None:
        with (out / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerows(rows)

    units = [{"serial": u.serial, "line": LINE["code"], "built_at": _iso(u.built_at), "batch": u.batch, "paint": u.paint}
             for u in res.units]
    write_csv("units.csv", ["serial", "line", "built_at", "batch", "paint"], units)

    pe, pp, insp, gt_rows, jobs = [], [], [], [], []
    for u in res.units:
        for st in u.route:
            row = {"serial": u.serial, "station": st["station"], "equipment": st["equipment"],
                   "started_at": _iso(st["started_at"]), "ended_at": _iso(st["ended_at"])}
            pe += maybe_defect(row, None, "station", "started_at", "serial")
            for name, (value, unit) in st["params"].items():
                prow = {"serial": u.serial, "station": st["station"], "parameter": name, "value": f"{value}", "unit": unit}
                pp += maybe_defect(prow, "value", None, None, "serial")
        cam = next(s for s in u.route if s["station"] == "S50")
        for loc in LOCATIONS:
            code = loc["code"]
            fname = f"images/{u.serial}_{code}.png"
            scene = {"gap_mm": u.true_gaps[code], "mm_per_px": MM_PER_PX, **u.scene[code]}
            jobs.append((fname, scene))
            irow = {"image_file": fname, "serial": u.serial, "location": code, "camera": "CAM-501",
                    "captured_at": _iso(cam["started_at"]), "calibration_ref": "CAL-CAM501-001"}
            insp.append(irow)
            gt_rows.append({"image_file": fname, "true_gap_mm": f"{u.true_gaps[code]:.5f}",
                            "generator_version": GENERATOR_VERSION, "scene_json": json.dumps(scene, sort_keys=True)})

    write_csv("production_events.csv", ["serial", "station", "equipment", "started_at", "ended_at"], pe)
    write_csv("process_parameters.csv", ["serial", "station", "parameter", "value", "unit"], pp)
    write_csv("inspections.csv", ["image_file", "serial", "location", "camera", "captured_at", "calibration_ref"], insp)
    eq_rows = [{"equipment": e["equipment"], "occurred_at": _iso(e["occurred_at"]), "kind": e["kind"],
                "description": e["description"]} for e in res.equipment_events]
    write_csv("equipment_events.csv", ["equipment", "occurred_at", "kind", "description"], eq_rows)
    cal_from = res.units[0].built_at - timedelta(hours=2) if res.units else datetime.now(UTC)
    write_csv("calibration.csv", ["reference", "camera", "mm_per_px", "method", "valid_from"],
              [{"reference": "CAL-CAM501-001", "camera": "CAM-501", "mm_per_px": f"{MM_PER_PX}",
                "method": "simulated reference target (known pitch)", "valid_from": _iso(cal_from)}])

    # Ground truth: kept apart from the production export.
    gt_dir = out / "ground_truth"
    gt_dir.mkdir(exist_ok=True)
    with (gt_dir / "gaps.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["image_file", "true_gap_mm", "generator_version", "scene_json"])
        w.writeheader()
        w.writerows(gt_rows)
    scenario = {
        "faults": [
            {"kind": f.kind, "target": f.target, "start_index": f.start_index, "magnitude": f.magnitude,
             "start_serial": next((u.serial for u in res.units if u.index == f.start_index), None),
             "description": f.description}
            for f in res.config.faults
        ],
        "realigned": list(res.config.realigned),
        "config": res.config.to_dict(),
        "simulator_version": res.simulator_version,
    }
    (gt_dir / "scenario.json").write_text(json.dumps(scenario, indent=2, default=str))

    if render:
        if workers > 1:
            with ProcessPoolExecutor(max_workers=workers) as ex:
                for path, png, _ in ex.map(_render_job, jobs, chunksize=16):
                    (out / path).write_bytes(png)
        else:
            for job in jobs:
                path, png, _ = _render_job(job)
                (out / path).write_bytes(png)

    files = {}
    for name in ["units.csv", "production_events.csv", "process_parameters.csv", "inspections.csv",
                 "equipment_events.csv", "calibration.csv"]:
        files[name] = {"sha256": _sha256(out / name), "rows": sum(1 for _ in (out / name).open()) - 1}
    manifest = {
        "format": EXPORT_FORMAT,
        "dataset_key": dataset_key,
        "provenance": "simulated",
        "simulator_version": res.simulator_version,
        "generator_version": GENERATOR_VERSION,
        "created_at": _iso(datetime.now(UTC)),
        "seed": res.config.seed,
        "n_units": len(res.units),
        "unit_range": list(unit_range) if unit_range else None,
        "n_images": len(jobs),
        "line": LINE,
        "stations": STATIONS,
        "equipment": EQUIPMENT,
        "paints": [{"code": c, "name": v["name"], "metallic": bool(v["metallic"])} for c, v in PAINTS.items()],
        "locations": [{k: v for k, v in loc.items() if k in ("code", "name", "description", "nominal_mm",
                                                             "lower_tol_mm", "upper_tol_mm")} for loc in LOCATIONS],
        "dq_defect_rate": dq_defect_rate,
        "injected_defects": injected,
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
