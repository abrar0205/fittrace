import json
import shutil

import pytest
from sqlalchemy import func, select

from app.domain import models as m
from app.pipelines.measure import run_measurement_pipeline
from app.pipelines.mes_import import run_mes_import

from .conftest import DATA_DIR, KEY, N_UNITS

pytestmark = pytest.mark.integration


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_import_loads_valid_records_and_audits_rejects(seeded, db):
    run = db.get(m.PipelineRun, seeded["import_run"])
    inj = seeded["manifest"]["injected_defects"]
    assert run.status == "succeeded"
    assert run.records_rejected > 0
    ds = db.scalar(select(m.Dataset).where(m.Dataset.key == KEY))
    assert count(db, m.ProductionUnit, m.ProductionUnit.dataset_id == ds.id) == N_UNITS
    errors = list(db.scalars(select(m.PipelineError).where(m.PipelineError.pipeline_run_id == run.id)))
    assert errors and all(e.reason for e in errors)
    # Each injected orphan reference produces at least one auditable reject naming the bogus serial.
    orphan_errors = [e for e in errors if "SIM-99999" in e.reason]
    assert len(orphan_errors) == inj["orphan_reference"]
    # Exact duplicates are counted as duplicates, never loaded twice.
    assert run.records_duplicate >= inj["exact_duplicate"]
    assert count(db, m.ProductionEvent) == db.scalar(
        select(func.count(func.distinct(func.concat(m.ProductionEvent.unit_id, "-", m.ProductionEvent.station_id)))))


def test_foreign_keys_and_provenance_intact(seeded, db):
    ds = db.scalar(select(m.Dataset).where(m.Dataset.key == KEY))
    assert ds.kind == "synthetic" and "not real factory data" in ds.provenance
    orphans = db.scalar(select(func.count()).select_from(m.InspectionImage)
                        .outerjoin(m.ProductionUnit, m.ProductionUnit.id == m.InspectionImage.unit_id)
                        .where(m.ProductionUnit.id.is_(None)))
    assert orphans == 0
    assert count(db, m.GroundTruthGap) == count(db, m.InspectionImage)
    assert count(db, m.FaultInjection, m.FaultInjection.dataset_id == ds.id) == 1


def test_reimport_is_idempotent(seeded, db):
    before = {t: count(db, t) for t in (m.ProductionUnit, m.ProductionEvent, m.ProcessParameter, m.InspectionImage,
                                        m.EquipmentEvent)}
    rid = run_mes_import(seeded["dir"], KEY)
    db.expire_all()
    run = db.get(m.PipelineRun, rid)
    assert run.status == "skipped" and run.records_loaded == 0 and run.records_skipped > 0
    assert {t: count(db, t) for t in before} == before


def test_row_level_idempotency_when_file_bytes_change(seeded, db, tmp_path):
    """Same records in a re-serialised file (new checksum) must not create duplicates."""
    copy = DATA_DIR / "raw" / "reserialised"
    shutil.copytree(seeded["dir"], copy, ignore=shutil.ignore_patterns("images"))
    (copy / "images").symlink_to(seeded["dir"] / "images", target_is_directory=True)
    p = copy / "equipment_events.csv"
    p.write_text(p.read_text().replace("\n", "\r\n"))
    man = json.loads((copy / "manifest.json").read_text())
    from app.pipelines.mes_import import sha256_file

    man["files"]["equipment_events.csv"]["sha256"] = sha256_file(p)
    (copy / "manifest.json").write_text(json.dumps(man))
    before = count(db, m.EquipmentEvent)
    rid = run_mes_import(copy, KEY)
    db.expire_all()
    run = db.get(m.PipelineRun, rid)
    assert run.status in ("succeeded", "skipped") and run.records_loaded == 0
    assert count(db, m.EquipmentEvent) == before


def test_checksum_mismatch_fails_without_partial_data(seeded, db):
    bad = DATA_DIR / "raw" / "corrupt"
    shutil.copytree(seeded["dir"], bad, ignore=shutil.ignore_patterns("images"))
    p = bad / "process_parameters.csv"
    p.write_text("\n".join(p.read_text().splitlines()[:-5]) + "\n")
    rid = run_mes_import(bad, "corrupt-ds")
    db.expire_all()
    run = db.get(m.PipelineRun, rid)
    assert run.status == "failed" and "checksum mismatch" in run.error_message
    assert db.scalar(select(m.Dataset).where(m.Dataset.key == "corrupt-ds")) is None


def test_quality_gate_rolls_back_everything(engine, db):
    from fittrace.simulation.export import write_export
    from fittrace.simulation.factory import SimConfig, simulate

    out = DATA_DIR / "raw" / "dirty"
    write_export(simulate(SimConfig(seed=9, n_units=40)), out, "dirty-ds", dq_defect_rate=0.4, workers=1)
    rid = run_mes_import(out, "dirty-ds")
    db.expire_all()
    run = db.get(m.PipelineRun, rid)
    assert run.status == "failed" and "quality gate" in run.error_message and run.records_loaded == 0
    assert db.scalar(select(m.Dataset).where(m.Dataset.key == "dirty-ds")) is None
    assert count(db, m.PipelineError, m.PipelineError.pipeline_run_id == rid) > 0  # rejects stay auditable


def test_measurement_pipeline_accuracy_and_resume(seeded, db):
    run = db.get(m.PipelineRun, seeded["measure_run"])
    assert run.status == "succeeded" and run.records_loaded == 2 * N_UNITS
    rows = db.execute(select(m.Measurement.gap_mm, m.GroundTruthGap.true_gap_mm)
                      .join(m.InspectionRun, m.InspectionRun.id == m.Measurement.run_id)
                      .join(m.InspectionImage, m.InspectionImage.current_run_id == m.InspectionRun.id)
                      .join(m.GroundTruthGap, m.GroundTruthGap.image_id == m.InspectionRun.image_id)
                      .where(m.InspectionRun.trigger == "pipeline")).all()
    errs = [g - t for g, t in rows]
    assert len(errs) == 2 * N_UNITS
    assert 0.010 < sum(errs) / len(errs) < 0.040  # documented hem-shading bias
    again = run_measurement_pipeline(KEY)
    db.expire_all()
    assert db.get(m.PipelineRun, again).status == "skipped"
