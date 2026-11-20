"""ETL: MES-style export directory -> PostgreSQL.

Guarantees
----------
* **Atomic**: all business rows of one run are written in a single
  transaction. A failure (exception or quality gate) rolls everything back;
  the run record and its error are written in a separate transaction so the
  failure stays visible.
* **Idempotent**: files already imported for the dataset (same kind + SHA-256)
  are skipped; rows use natural-key ``ON CONFLICT DO NOTHING``. Re-running the
  same export never creates duplicate business records.
* **Incremental**: a later export with new units only inserts the new rows.
* **Auditable**: every rejected row is stored with file, row number, field,
  reason and the raw values.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import cv2
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.logging import log
from app.domain import models as m
from fittrace.etl.validation import Context, ValidationReport, parse_float, parse_ts, validate_rows

logger = logging.getLogger("fittrace.etl.mes_import")
PIPELINE = "mes_import"

FILE_ORDER = [
    ("units", "units.csv"),
    ("production_events", "production_events.csv"),
    ("process_parameters", "process_parameters.csv"),
    ("equipment_events", "equipment_events.csv"),
    ("inspections", "inspections.csv"),
]


class QualityGateError(Exception):
    pass


@dataclass
class RunStats:
    records_in: int = 0
    loaded: int = 0
    rejected: int = 0
    duplicate: int = 0
    skipped: int = 0
    per_file: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    dq: list[dict] = field(default_factory=list)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(p: Path) -> list[dict]:
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def _ins(db: Session, model, rows: list[dict], conflict: list[str]) -> int:
    """Bulk insert with ON CONFLICT DO NOTHING; returns the number inserted."""
    if not rows:
        return 0
    total = 0
    for i in range(0, len(rows), 2000):
        stmt = insert(model).values(rows[i : i + 2000]).on_conflict_do_nothing(index_elements=conflict)
        stmt = stmt.returning(model.__table__.c[list(model.__table__.primary_key.columns)[0].name])
        total += len(db.execute(stmt).fetchall())
    return total


def _ensure_reference(db: Session, manifest: dict, export: Path, dataset: m.Dataset) -> None:
    line = manifest["line"]
    db.execute(insert(m.ProductionLine).values(code=line["code"], name=line["name"]).on_conflict_do_nothing())
    line_id = db.scalar(select(m.ProductionLine.id).where(m.ProductionLine.code == line["code"]))
    for s in manifest["stations"]:
        db.execute(insert(m.Station).values(line_id=line_id, code=s["code"], name=s["name"], sequence=s["sequence"])
                   .on_conflict_do_nothing())
    st = {c: i for c, i in db.execute(select(m.Station.code, m.Station.id).where(m.Station.line_id == line_id))}
    for e in manifest["equipment"]:
        db.execute(insert(m.Equipment).values(station_id=st[e["station"]], code=e["code"], kind=e["kind"], name=e["name"])
                   .on_conflict_do_nothing())
    for loc in manifest["locations"]:
        db.execute(insert(m.MeasurementLocation).values(code=loc["code"], name=loc["name"], description=loc["description"])
                   .on_conflict_do_nothing())
        loc_id = db.scalar(select(m.MeasurementLocation.id).where(m.MeasurementLocation.code == loc["code"]))
        db.execute(insert(m.ToleranceSpecification).values(
            location_id=loc_id, version=1, nominal_mm=loc["nominal_mm"], lower_tol_mm=loc["lower_tol_mm"],
            upper_tol_mm=loc["upper_tol_mm"], valid_from=datetime(2020, 1, 1, tzinfo=UTC)).on_conflict_do_nothing())
    for p in manifest.get("paints", []):
        db.execute(insert(m.PaintCode).values(code=p["code"], name=p["name"], metallic=bool(p.get("metallic")))
                   .on_conflict_do_nothing())
    cam = {c: i for c, i in db.execute(select(m.Equipment.code, m.Equipment.id))}
    for row in _read_csv(export / "calibration.csv"):
        db.execute(insert(m.CalibrationRecord).values(
            dataset_id=dataset.id, reference=row["reference"], camera_id=cam[row["camera"]],
            mm_per_px=parse_float(row["mm_per_px"]), method=row["method"], valid_from=parse_ts(row["valid_from"]),
        ).on_conflict_do_nothing())


def _context(db: Session, dataset_id: int, unit_serials: set[str]) -> Context:
    existing = set(db.scalars(select(m.ProductionUnit.serial).where(m.ProductionUnit.dataset_id == dataset_id)))
    return Context(
        stations=frozenset(db.scalars(select(m.Station.code))),
        equipment={c: s for c, s in db.execute(select(m.Equipment.code, m.Station.code).join(m.Station))},
        serials=frozenset(unit_serials | existing),
        locations=frozenset(db.scalars(select(m.MeasurementLocation.code))),
        calibrations=frozenset(db.scalars(select(m.CalibrationRecord.reference)
                                          .where(m.CalibrationRecord.dataset_id == dataset_id))),
        paints=frozenset(db.scalars(select(m.PaintCode.code))),
    )


def _record_report(stats: RunStats, fname: str, rep: ValidationReport) -> None:
    rejected_rows = {r.row_number for r in rep.rejects}
    stats.records_in += rep.rows_in
    stats.rejected += len(rejected_rows)
    stats.duplicate += rep.duplicates
    stats.per_file[fname] = {"rows_in": rep.rows_in, "valid": len(rep.records), "rejected": len(rejected_rows),
                             "duplicates_in_file": rep.duplicates}
    for r in rep.rejects:
        stats.errors.append({"file_name": fname, "row_number": r.row_number, "field": r.field, "reason": r.reason,
                             "raw": r.raw})


def _load(db: Session, export: Path, dataset: m.Dataset, run_id: int, stats: RunStats, data_dir: Path) -> None:
    already = {(k, s) for k, s in db.execute(select(m.DatasetImport.file_kind, m.DatasetImport.sha256)
                                             .where(m.DatasetImport.dataset_id == dataset.id))}
    reports: dict[str, ValidationReport] = {}
    raw_units = _read_csv(export / "units.csv")
    ctx = _context(db, dataset.id, {r["serial"] for r in raw_units if r.get("serial")})
    for kind, fname in FILE_ORDER:
        p = export / fname
        digest = sha256_file(p)
        rows = raw_units if kind == "units" else _read_csv(p)
        if (kind, digest) in already:
            stats.skipped += len(rows)
            stats.per_file[fname] = {"rows_in": len(rows), "skipped": True, "reason": "identical file already imported"}
            continue
        rep = validate_rows(kind, rows, ctx)
        reports[kind] = rep
        _record_report(stats, fname, rep)
        stats.imports.append({"file_name": fname, "file_kind": kind, "sha256": digest, "rows": len(rows)})

    if stats.records_in and stats.rejected / stats.records_in > get_settings().reject_rate_gate:
        raise QualityGateError(
            f"reject rate {stats.rejected / stats.records_in:.1%} exceeds gate {get_settings().reject_rate_gate:.0%}")

    line_ids = {c: i for c, i in db.execute(select(m.ProductionLine.code, m.ProductionLine.id))}
    st_ids = {c: i for c, i in db.execute(select(m.Station.code, m.Station.id))}
    eq_ids = {c: i for c, i in db.execute(select(m.Equipment.code, m.Equipment.id))}

    def done(kind: str, n_valid: int, inserted: int) -> None:
        stats.loaded += inserted
        stats.duplicate += n_valid - inserted
        stats.per_file[dict(FILE_ORDER)[kind]]["inserted"] = inserted

    if rep := reports.get("units"):
        rows = [{"dataset_id": dataset.id, "serial": r["serial"], "line_id": line_ids[r["line"]], "built_at": r["built_at"],
                 "batch_code": r["batch"], "paint_code": r.get("paint"), "pipeline_run_id": run_id} for r in rep.records]
        done("units", len(rows), _ins(db, m.ProductionUnit, rows, ["dataset_id", "serial"]))
    unit_ids = {s: i for s, i in db.execute(select(m.ProductionUnit.serial, m.ProductionUnit.id)
                                            .where(m.ProductionUnit.dataset_id == dataset.id))}
    if rep := reports.get("production_events"):
        rows = [{"unit_id": unit_ids[r["serial"]], "station_id": st_ids[r["station"]], "equipment_id": eq_ids[r["equipment"]],
                 "started_at": r["started_at"], "ended_at": r["ended_at"], "pipeline_run_id": run_id} for r in rep.records]
        done("production_events", len(rows), _ins(db, m.ProductionEvent, rows, ["unit_id", "station_id"]))
    ev_ids = {(u, s): i for u, s, i in db.execute(
        select(m.ProductionUnit.serial, m.Station.code, m.ProductionEvent.id)
        .join(m.ProductionUnit, m.ProductionUnit.id == m.ProductionEvent.unit_id)
        .join(m.Station, m.Station.id == m.ProductionEvent.station_id)
        .where(m.ProductionUnit.dataset_id == dataset.id))}
    if rep := reports.get("process_parameters"):
        rows, missing = [], 0
        for r in rep.records:
            ev = ev_ids.get((r["serial"], r["station"]))
            if ev is None:
                missing += 1
                stats.errors.append({"file_name": "process_parameters.csv", "row_number": None, "field": "serial",
                                     "reason": f"no production event for {r['serial']} at {r['station']} (event row rejected)",
                                     "raw": {k: str(v) for k, v in r.items()}})
                continue
            rows.append({"production_event_id": ev, "name": r["parameter"], "value": r["value"], "unit": r["unit"]})
        stats.rejected += missing
        done("process_parameters", len(rows), _ins(db, m.ProcessParameter, rows, ["production_event_id", "name"]))
    if rep := reports.get("equipment_events"):
        rows = [{"dataset_id": dataset.id, "equipment_id": eq_ids[r["equipment"]], "occurred_at": r["occurred_at"],
                 "kind": r["kind"], "description": r["description"]} for r in rep.records]
        done("equipment_events", len(rows),
             _ins(db, m.EquipmentEvent, rows, ["dataset_id", "equipment_id", "occurred_at", "kind"]))
    if rep := reports.get("inspections"):
        loc_ids = {c: i for c, i in db.execute(select(m.MeasurementLocation.code, m.MeasurementLocation.id))}
        cal_ids = {c: i for c, i in db.execute(select(m.CalibrationRecord.reference, m.CalibrationRecord.id)
                                               .where(m.CalibrationRecord.dataset_id == dataset.id))}
        rows = []
        for r in rep.records:
            img_path = (export / r["image_file"]).resolve()
            if not img_path.is_file():
                stats.rejected += 1
                stats.errors.append({"file_name": "inspections.csv", "row_number": None, "field": "image_file",
                                     "reason": "image file missing from export", "raw": {"image_file": r["image_file"]}})
                continue
            img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                stats.rejected += 1
                stats.errors.append({"file_name": "inspections.csv", "row_number": None, "field": "image_file",
                                     "reason": "image file could not be decoded", "raw": {"image_file": r["image_file"]}})
                continue
            rows.append({"dataset_id": dataset.id, "unit_id": unit_ids[r["serial"]], "location_id": loc_ids[r["location"]],
                         "calibration_id": cal_ids[r["calibration_ref"]], "camera_id": eq_ids[r["camera"]],
                         "storage_path": str(img_path.relative_to(data_dir.resolve())), "sha256": sha256_file(img_path),
                         "width": int(img.shape[1]), "height": int(img.shape[0]), "captured_at": r["captured_at"],
                         "pipeline_run_id": run_id})
        done("inspections", len(rows), _ins(db, m.InspectionImage, rows, ["dataset_id", "unit_id", "location_id"]))

    _load_ground_truth(db, export, dataset, data_dir)
    _data_quality_checks(db, dataset, stats)


def _load_ground_truth(db: Session, export: Path, dataset: m.Dataset, data_dir: Path) -> None:
    gt_file = export / "ground_truth" / "gaps.csv"
    if gt_file.is_file():
        paths = {p: i for p, i in db.execute(select(m.InspectionImage.storage_path, m.InspectionImage.id)
                                             .where(m.InspectionImage.dataset_id == dataset.id))}
        rows = []
        for r in _read_csv(gt_file):
            key = str((export / r["image_file"]).resolve().relative_to(data_dir.resolve()))
            if key in paths:
                rows.append({"image_id": paths[key], "true_gap_mm": float(r["true_gap_mm"]),
                             "generator_version": r["generator_version"], "scene": json.loads(r["scene_json"])})
        _ins(db, m.GroundTruthGap, rows, ["image_id"])
    sc_file = export / "ground_truth" / "scenario.json"
    if sc_file.is_file():
        sc = json.loads(sc_file.read_text())
        rows = [{"dataset_id": dataset.id, "kind": f["kind"], "target_code": f["target"], "start_serial": f["start_serial"],
                 "start_index": f["start_index"], "magnitude": f["magnitude"], "description": f["description"]}
                for f in sc.get("faults", [])]
        _ins(db, m.FaultInjection, rows, ["dataset_id", "kind", "target_code", "start_index"])


def _data_quality_checks(db: Session, dataset: m.Dataset, stats: RunStats) -> None:
    n_units = db.scalar(select(func.count()).select_from(m.ProductionUnit).where(m.ProductionUnit.dataset_id == dataset.id)) or 0
    n_stations = db.scalar(select(func.count()).select_from(m.Station)) or 0
    incomplete = db.scalar(
        select(func.count()).select_from(
            select(m.ProductionUnit.id).outerjoin(m.ProductionEvent, m.ProductionEvent.unit_id == m.ProductionUnit.id)
            .where(m.ProductionUnit.dataset_id == dataset.id).group_by(m.ProductionUnit.id)
            .having(func.count(m.ProductionEvent.id) < n_stations).subquery())) or 0
    no_image = db.scalar(
        select(func.count()).select_from(m.ProductionUnit)
        .where(m.ProductionUnit.dataset_id == dataset.id,
               ~select(m.InspectionImage.id).where(m.InspectionImage.unit_id == m.ProductionUnit.id).exists())) or 0
    stats.dq += [
        {"check_name": "route_completeness", "passed": incomplete == 0,
         "observed": {"units": n_units, "units_with_incomplete_route": incomplete}},
        {"check_name": "inspection_coverage", "passed": no_image == 0,
         "observed": {"units": n_units, "units_without_inspection": no_image}},
        {"check_name": "reject_rate", "passed": (stats.rejected / max(1, stats.records_in)) <= get_settings().reject_rate_gate,
         "observed": {"rejected": stats.rejected, "records_in": stats.records_in,
                      "rate": round(stats.rejected / max(1, stats.records_in), 5)}},
    ]


def run_mes_import(export_dir: str | Path, dataset_key: str, dataset_name: str | None = None,
                   retry_of_id: int | None = None, job_id: int | None = None) -> int:
    """Execute one import run; returns the pipeline_run id."""
    settings = get_settings()
    data_dir = settings.data_dir
    export = Path(export_dir)
    if not export.is_absolute():
        export = data_dir / export
    SessionLocal = get_sessionmaker()
    t0 = time.perf_counter()
    with SessionLocal() as db:
        ds = db.scalar(select(m.Dataset).where(m.Dataset.key == dataset_key))
        run = m.PipelineRun(pipeline=PIPELINE, dataset_id=ds.id if ds else None, status="running",
                            source_uri=str(export.relative_to(data_dir)) if export.is_relative_to(data_dir) else str(export),
                            params={"dataset_key": dataset_key}, retry_of_id=retry_of_id, job_id=job_id)
        db.add(run)
        db.commit()
        run_id = run.id
    log(logger, logging.INFO, "pipeline started", pipeline=PIPELINE, run_id=run_id, source=str(export))
    stats = RunStats()
    status, error = "succeeded", None
    try:
        manifest_p = export / "manifest.json"
        if not manifest_p.is_file():
            raise FileNotFoundError(f"manifest.json not found in {export}")
        manifest = json.loads(manifest_p.read_text())
        for fname, meta in manifest.get("files", {}).items():
            if not (export / fname).is_file():
                raise FileNotFoundError(f"{fname} listed in manifest but missing")
            if sha256_file(export / fname) != meta["sha256"]:
                raise ValueError(f"checksum mismatch for {fname}: file differs from manifest (truncated or modified)")
        with SessionLocal() as db, db.begin():
            ds = db.scalar(select(m.Dataset).where(m.Dataset.key == dataset_key))
            if ds is None:
                ds = m.Dataset(key=dataset_key, name=dataset_name or dataset_key,
                               kind="synthetic" if manifest.get("provenance") == "simulated" else "real",
                               provenance=f"Generated by {manifest.get('simulator_version')} / {manifest.get('generator_version')}, "
                                          f"seed {manifest.get('seed')}. Simulated production history - not real factory data.",
                               license="MIT (generated by this project)", source_uri=str(export.name),
                               meta={"seed": manifest.get("seed"), "dq_defect_rate": manifest.get("dq_defect_rate")})
                db.add(ds)
                db.flush()
            db.execute(m.PipelineRun.__table__.update().where(m.PipelineRun.id == run_id).values(dataset_id=ds.id))
            _ensure_reference(db, manifest, export, ds)
            _load(db, export, ds, run_id, stats, data_dir)
            for imp in stats.imports:
                db.execute(insert(m.DatasetImport).values(dataset_id=ds.id, pipeline_run_id=run_id, **imp)
                           .on_conflict_do_nothing())
        if stats.loaded == 0 and stats.skipped > 0 and stats.rejected == 0:
            status = "skipped"
    except QualityGateError as e:
        status, error = "failed", f"quality gate: {e}; no records were loaded"
    except Exception as e:  # noqa: BLE001 - every failure must be recorded
        status, error = "failed", f"{type(e).__name__}: {e}"
        logger.exception("pipeline failed")
    duration = time.perf_counter() - t0
    with SessionLocal() as db, db.begin():
        run = db.get(m.PipelineRun, run_id)
        assert run is not None
        run.status = status
        run.error_message = error
        run.finished_at = datetime.now(UTC)
        run.records_in = stats.records_in
        run.records_loaded = stats.loaded if status != "failed" else 0
        run.records_rejected = stats.rejected
        run.records_duplicate = stats.duplicate if status != "failed" else 0
        run.records_skipped = stats.skipped
        run.metrics = {"duration_s": round(duration, 3), "files": stats.per_file}
        for e in stats.errors[:5000]:
            db.add(m.PipelineError(pipeline_run_id=run_id, file_name=e["file_name"], row_number=e["row_number"],
                                   field=e["field"], reason=e["reason"], raw={k: str(v) for k, v in e["raw"].items()}))
        if status == "succeeded":
            for d in stats.dq:
                db.add(m.DataQualityResult(pipeline_run_id=run_id, **d))
    log(logger, logging.INFO, "pipeline finished", pipeline=PIPELINE, run_id=run_id, status=status,
        loaded=stats.loaded, rejected=stats.rejected, duration_s=round(duration, 3))
    return run_id
