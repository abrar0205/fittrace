"""PostgreSQL schema (SQLAlchemy 2.0 typed ORM).

Groups: reference/production, inspection, simulation ground truth, quality
investigation, data infrastructure, jobs. Every business table carries a
``dataset_id`` (directly or through its parent) so synthetic and real sources
can never be joined into one production history by accident.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def ts(nullable: bool = False, default_now: bool = False):
    kw = {"server_default": func.now()} if default_now else {}
    return mapped_column(DateTime(timezone=True), nullable=nullable, **kw)


# --------------------------------------------------------------------------- reference & production


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # synthetic | real
    provenance: Mapped[str] = mapped_column(Text)
    license: Mapped[str | None] = mapped_column(String(200))
    source_uri: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = ts(default_now=True)
    __table_args__ = (CheckConstraint("kind in ('synthetic','real')", name="ck_dataset_kind"),)


class ProductionLine(Base):
    __tablename__ = "production_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))


class Station(Base):
    __tablename__ = "stations"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    sequence: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("line_id", "code"),)


class Equipment(Base):
    __tablename__ = "equipment"
    id: Mapped[int] = mapped_column(primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    code: Mapped[str] = mapped_column(String(40), unique=True)
    kind: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    station: Mapped[Station] = relationship()
    __table_args__ = (CheckConstraint("kind in ('fixture','tool','camera')", name="ck_equipment_kind"),)


class ProductionUnit(Base):
    __tablename__ = "production_units"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    serial: Mapped[str] = mapped_column(String(40))
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id"))
    built_at: Mapped[datetime] = ts()
    batch_code: Mapped[str] = mapped_column(String(40))
    pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    __table_args__ = (
        UniqueConstraint("dataset_id", "serial"),
        Index("ix_units_dataset_built", "dataset_id", "built_at"),
    )


class ProductionEvent(Base):
    __tablename__ = "production_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("production_units.id", ondelete="CASCADE"))
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    started_at: Mapped[datetime] = ts()
    ended_at: Mapped[datetime] = ts()
    pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    __table_args__ = (
        UniqueConstraint("unit_id", "station_id"),
        Index("ix_events_equipment_started", "equipment_id", "started_at"),
        CheckConstraint("ended_at >= started_at", name="ck_event_order"),
    )


class ProcessParameter(Base):
    __tablename__ = "process_parameters"
    id: Mapped[int] = mapped_column(primary_key=True)
    production_event_id: Mapped[int] = mapped_column(ForeignKey("production_events.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("production_event_id", "name"),)


class EquipmentEvent(Base):
    __tablename__ = "equipment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    equipment_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    occurred_at: Mapped[datetime] = ts()
    kind: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (
        UniqueConstraint("dataset_id", "equipment_id", "occurred_at", "kind"),
        Index("ix_eqevents_equipment_time", "equipment_id", "occurred_at"),
    )


# --------------------------------------------------------------------------- inspection


class MeasurementLocation(Base):
    __tablename__ = "measurement_locations"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class ToleranceSpecification(Base):
    __tablename__ = "tolerance_specifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("measurement_locations.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    nominal_mm: Mapped[float] = mapped_column(Float)
    lower_tol_mm: Mapped[float] = mapped_column(Float)
    upper_tol_mm: Mapped[float] = mapped_column(Float)
    valid_from: Mapped[datetime] = ts()
    __table_args__ = (
        UniqueConstraint("location_id", "version"),
        CheckConstraint("lower_tol_mm <= 0 and upper_tol_mm >= 0", name="ck_tol_signs"),
    )


class CalibrationRecord(Base):
    __tablename__ = "calibration_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    reference: Mapped[str] = mapped_column(String(60))
    camera_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    mm_per_px: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(Text)
    valid_from: Mapped[datetime] = ts()
    valid_to: Mapped[datetime | None] = ts(nullable=True)
    __table_args__ = (UniqueConstraint("dataset_id", "reference"), CheckConstraint("mm_per_px > 0", name="ck_cal_pos"))


class InspectionImage(Base):
    __tablename__ = "inspection_images"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("production_units.id", ondelete="CASCADE"))
    location_id: Mapped[int] = mapped_column(ForeignKey("measurement_locations.id"))
    calibration_id: Mapped[int | None] = mapped_column(ForeignKey("calibration_records.id"))
    camera_id: Mapped[int] = mapped_column(ForeignKey("equipment.id"))
    storage_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = ts()
    current_run_id: Mapped[int | None] = mapped_column(ForeignKey("inspection_runs.id", use_alter=True, name="fk_image_current_run"))
    pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    __table_args__ = (
        UniqueConstraint("dataset_id", "unit_id", "location_id"),
        Index("ix_images_location_captured", "location_id", "captured_at"),
    )


class GroundTruthGap(Base):
    """Simulation ground truth. Read only by evaluation endpoints, never by measurement."""

    __tablename__ = "ground_truth_gaps"
    image_id: Mapped[int] = mapped_column(ForeignKey("inspection_images.id", ondelete="CASCADE"), primary_key=True)
    true_gap_mm: Mapped[float] = mapped_column(Float)
    generator_version: Mapped[str] = mapped_column(String(60))
    scene: Mapped[dict] = mapped_column(JSONB)


class AlgorithmVersion(Base):
    __tablename__ = "algorithm_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    version: Mapped[str] = mapped_column(String(20))
    params_hash: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = ts(default_now=True)
    __table_args__ = (UniqueConstraint("name", "version", "params_hash"),)


class InspectionRun(Base):
    __tablename__ = "inspection_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("inspection_images.id", ondelete="CASCADE"))
    algorithm_version_id: Mapped[int] = mapped_column(ForeignKey("algorithm_versions.id"))
    trigger: Mapped[str] = mapped_column(String(20))  # pipeline | interactive
    status: Mapped[str] = mapped_column(String(10))  # ok | failed
    failure_code: Mapped[str | None] = mapped_column(String(60))
    failure_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float] = mapped_column(Float)
    flags: Mapped[list] = mapped_column(JSONB, default=list)
    diagnostics: Mapped[dict] = mapped_column(JSONB, default=dict)
    overlay: Mapped[dict] = mapped_column(JSONB, default=dict)
    pipeline_run_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    created_at: Mapped[datetime] = ts(default_now=True)
    measurement: Mapped[Measurement | None] = relationship(back_populates="run", uselist=False)
    algorithm: Mapped[AlgorithmVersion] = relationship()
    __table_args__ = (
        Index("ix_runs_image_created", "image_id", "created_at"),
        CheckConstraint("status in ('ok','failed')", name="ck_run_status"),
    )


class Measurement(Base):
    __tablename__ = "measurements"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("inspection_runs.id", ondelete="CASCADE"), unique=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("measurement_locations.id"))
    tolerance_spec_id: Mapped[int] = mapped_column(ForeignKey("tolerance_specifications.id"))
    gap_px: Mapped[float] = mapped_column(Float)
    gap_mm: Mapped[float | None] = mapped_column(Float)
    std_error_mm: Mapped[float | None] = mapped_column(Float)
    deviation_mm: Mapped[float | None] = mapped_column(Float)
    angle_deg: Mapped[float] = mapped_column(Float)
    calibrated: Mapped[bool] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(20))
    run: Mapped[InspectionRun] = relationship(back_populates="measurement")
    __table_args__ = (
        Index("ix_measurements_status", "status"),
        CheckConstraint("status in ('in_tolerance','out_low','out_high','not_evaluable')", name="ck_meas_status"),
    )


# --------------------------------------------------------------------------- simulation ground truth


class FaultInjection(Base):
    __tablename__ = "fault_injections"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    kind: Mapped[str] = mapped_column(String(40))
    target_code: Mapped[str] = mapped_column(String(40))
    start_serial: Mapped[str | None] = mapped_column(String(40))
    start_index: Mapped[int] = mapped_column(Integer)
    magnitude: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("dataset_id", "kind", "target_code", "start_index"),)


# --------------------------------------------------------------------------- investigations


class QualityInvestigation(Base):
    __tablename__ = "quality_investigations"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    trigger_run_id: Mapped[int] = mapped_column(ForeignKey("inspection_runs.id"))
    location_id: Mapped[int] = mapped_column(ForeignKey("measurement_locations.id"))
    status: Mapped[str] = mapped_column(String(30))  # shift_detected | no_sustained_shift
    method: Mapped[str] = mapped_column(String(80))
    method_version: Mapped[str] = mapped_column(String(20))
    params: Mapped[dict] = mapped_column(JSONB)
    change_point: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    limitations: Mapped[list] = mapped_column(JSONB)
    duration_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = ts(default_now=True)
    hypotheses: Mapped[list[ContributorHypothesis]] = relationship(
        back_populates="investigation", order_by="ContributorHypothesis.rank.nulls_last()", cascade="all, delete-orphan")
    evidence: Mapped[list[InvestigationEvidence]] = relationship(cascade="all, delete-orphan")


class ContributorHypothesis(Base):
    __tablename__ = "contributor_hypotheses"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("quality_investigations.id", ondelete="CASCADE"))
    rank: Mapped[int | None] = mapped_column(Integer)
    factor_type: Mapped[str] = mapped_column(String(20))
    factor: Mapped[str] = mapped_column(String(80))
    level: Mapped[str | None] = mapped_column(String(80))
    station_code: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    effect_mm: Mapped[float | None] = mapped_column(Float)
    ci_low: Mapped[float | None] = mapped_column(Float)
    ci_high: Mapped[float | None] = mapped_column(Float)
    p_value: Mapped[float | None] = mapped_column(Float)
    q_value: Mapped[float | None] = mapped_column(Float)
    attributable_shift_mm: Mapped[float | None] = mapped_column(Float)
    explained_fraction: Mapped[float | None] = mapped_column(Float)
    significant: Mapped[bool] = mapped_column(Boolean, default=False)
    n_pre: Mapped[int] = mapped_column(Integer)
    n_post: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    investigation: Mapped[QualityInvestigation] = relationship(back_populates="hypotheses")


class InvestigationEvidence(Base):
    __tablename__ = "investigation_evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("quality_investigations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)


class CorrectiveAction(Base):
    __tablename__ = "corrective_actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    investigation_id: Mapped[int] = mapped_column(ForeignKey("quality_investigations.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))
    target_code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = ts(default_now=True)


class VerificationRun(Base):
    __tablename__ = "verification_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    corrective_action_id: Mapped[int] = mapped_column(ForeignKey("corrective_actions.id", ondelete="CASCADE"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    status: Mapped[str] = mapped_column(String(20))
    n_units: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = ts(default_now=True)
    finished_at: Mapped[datetime | None] = ts(nullable=True)


# --------------------------------------------------------------------------- data infrastructure


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline: Mapped[str] = mapped_column(String(60))
    dataset_id: Mapped[int | None] = mapped_column(ForeignKey("datasets.id"))
    source_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20))  # running | succeeded | failed | skipped
    started_at: Mapped[datetime] = ts(default_now=True)
    finished_at: Mapped[datetime | None] = ts(nullable=True)
    records_in: Mapped[int] = mapped_column(Integer, default=0)
    records_loaded: Mapped[int] = mapped_column(Integer, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, default=0)
    records_duplicate: Mapped[int] = mapped_column(Integer, default=0)
    records_skipped: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    retry_of_id: Mapped[int | None] = mapped_column(ForeignKey("pipeline_runs.id"))
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"))
    __table_args__ = (
        Index("ix_pipeline_runs_started", "started_at"),
        CheckConstraint("status in ('running','succeeded','failed','skipped')", name="ck_pipeline_status"),
    )


class DatasetImport(Base):
    __tablename__ = "dataset_imports"
    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int] = mapped_column(ForeignKey("datasets.id"))
    pipeline_run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id"))
    file_name: Mapped[str] = mapped_column(Text)
    file_kind: Mapped[str] = mapped_column(String(40))
    sha256: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(Integer)
    imported_at: Mapped[datetime] = ts(default_now=True)
    __table_args__ = (UniqueConstraint("dataset_id", "file_kind", "sha256"),)


class PipelineError(Base):
    __tablename__ = "pipeline_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    file_name: Mapped[str | None] = mapped_column(Text)
    row_number: Mapped[int | None] = mapped_column(Integer)
    field: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (Index("ix_pipeline_errors_run", "pipeline_run_id"),)


class DataQualityResult(Base):
    __tablename__ = "data_quality_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    pipeline_run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"))
    check_name: Mapped[str] = mapped_column(String(80))
    passed: Mapped[bool] = mapped_column(Boolean)
    observed: Mapped[dict] = mapped_column(JSONB)


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40))  # vision | investigation
    code_version: Mapped[str] = mapped_column(String(80))
    params: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = ts(default_now=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    message: Mapped[str | None] = mapped_column(Text)
    run_after: Mapped[datetime] = ts(default_now=True)
    created_at: Mapped[datetime] = ts(default_now=True)
    started_at: Mapped[datetime | None] = ts(nullable=True)
    finished_at: Mapped[datetime | None] = ts(nullable=True)
    __table_args__ = (
        Index("ix_jobs_queue", "status", "run_after"),
        CheckConstraint("status in ('queued','running','succeeded','failed')", name="ck_job_status"),
    )
