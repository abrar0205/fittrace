"""API contracts. Independent of the ORM: services map persistence rows to these."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")
ToleranceStatus = Literal["in_tolerance", "out_low", "out_high", "not_evaluable"]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(Schema, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Provenance(Schema):
    dataset_key: str
    dataset_kind: Literal["synthetic", "real"]
    simulated: bool
    statement: str


# --------------------------------------------------------------------------- health & meta


class Health(Schema):
    status: Literal["ok", "degraded"]
    database: Literal["ok", "unavailable"]
    version: str
    demo_readonly: bool


class DatasetOut(Schema):
    id: int
    key: str
    name: str
    kind: str
    provenance: str
    license: str | None
    created_at: datetime
    units: int
    images: int
    measured: int


class LocationOut(Schema):
    code: str
    name: str
    description: str
    nominal_mm: float
    lower_tol_mm: float
    upper_tol_mm: float
    lsl_mm: float
    usl_mm: float


# --------------------------------------------------------------------------- inspections


class PaintOut(Schema):
    code: str
    name: str
    metallic: bool


class InspectionListItem(Schema):
    image_id: int
    serial: str
    unit_id: int
    paint_code: str | None = None
    location: str
    captured_at: datetime
    run_status: Literal["ok", "failed"] | None
    gap_mm: float | None
    deviation_mm: float | None
    tolerance_status: ToleranceStatus | None
    flags: list[str]


class OverlayRow(Schema):
    y: float
    xl: float
    xr: float
    inlier: bool


class Overlay(Schema):
    rows: list[OverlayRow] = []
    left_line: list[list[float]] | None = None
    right_line: list[list[float]] | None = None
    measurement: dict[str, list[float]] | None = None
    roi: list[float] | None = None


class MeasurementOut(Schema):
    gap_px: float
    gap_mm: float | None
    std_error_mm: float | None
    deviation_mm: float | None
    angle_deg: float
    calibrated: bool
    status: ToleranceStatus


class InspectionRunOut(Schema):
    id: int
    trigger: str
    status: Literal["ok", "failed"]
    algorithm: str
    algorithm_version: str
    algorithm_params: dict[str, Any]
    failure_code: str | None
    failure_message: str | None
    duration_ms: float
    flags: list[str]
    diagnostics: dict[str, Any]
    overlay: Overlay
    measurement: MeasurementOut | None
    created_at: datetime
    is_current: bool


class CalibrationOut(Schema):
    reference: str
    camera: str
    mm_per_px: float
    method: str
    valid_from: datetime
    valid_to: datetime | None


class InspectionDetail(Schema):
    image_id: int
    serial: str
    unit_id: int
    paint: PaintOut | None
    dataset_key: str
    location: LocationOut
    captured_at: datetime
    image_url: str
    width: int
    height: int
    sha256: str
    calibration: CalibrationOut | None
    current_run: InspectionRunOut | None
    runs: list[InspectionRunOut]
    provenance: Provenance
    investigation_ids: list[int]
    neighbors: dict[str, int | None]


class RerunRequest(Schema):
    smoothing_sigma_px: float = Field(1.5, ge=0.0, le=6.0)
    row_step: int = Field(4, ge=1, le=32)
    min_edge_gradient: float = Field(2.0, ge=0.5, le=60.0)
    edge_snr: float = Field(6.0, ge=2.0, le=30.0)
    outlier_mad_k: float = Field(3.5, ge=1.5, le=10.0)


class GroundTruthComparison(Schema):
    image_id: int
    available: bool
    true_gap_mm: float | None
    measured_gap_mm: float | None
    error_um: float | None
    generator_version: str | None
    note: str


# --------------------------------------------------------------------------- analytics


class SeriesPoint(Schema):
    image_id: int
    serial: str
    built_at: datetime
    gap_mm: float | None
    deviation_mm: float | None
    tolerance_status: ToleranceStatus | None
    route: dict[str, str]
    batch: str


class SeriesOut(Schema):
    location: LocationOut
    points: list[SeriesPoint]
    failed_runs: int
    provenance: Provenance


class SpcOut(Schema):
    location: LocationOut
    applicable: bool
    n: int
    baseline_n: int
    center: float
    sigma_hat: float
    ucl: float
    lcl: float
    mr_bar: float
    mr_ucl: float
    values: list[float]
    moving_range: list[float | None]
    image_ids: list[int]
    serials: list[str]
    built_at: list[datetime]
    signals: list[list[str]]
    first_signal_index: int | None
    warnings: list[str]
    capability: dict[str, float | None] | None
    capability_note: str


class GroupStat(Schema):
    equipment: str
    n: int
    mean_mm: float
    sd_mm: float | None
    median_mm: float
    p05_mm: float
    p95_mm: float
    n_oot: int
    oot_rate: float
    values: list[float]


class StationComparisonOut(Schema):
    location: LocationOut
    station: str
    groups: list[GroupStat]
    anova_p: float | None
    kruskal_p: float | None
    note: str


class TrendBucket(Schema):
    location: str
    bucket: datetime
    n: int
    mean_deviation_mm: float | None
    sd_deviation_mm: float | None
    n_oot: int


class OverviewOut(Schema):
    dataset: DatasetOut | None
    locations: list[dict[str, Any]]
    latest_oot: list[dict[str, Any]]
    trend: list[TrendBucket]
    recent_investigations: list[dict[str, Any]]
    pipelines: list[dict[str, Any]]
    datasets: list[DatasetOut]
    provenance: Provenance | None


# --------------------------------------------------------------------------- traceability


class RouteStep(Schema):
    station: str
    station_name: str
    sequence: int
    equipment: str
    equipment_kind: str
    equipment_name: str
    started_at: datetime
    ended_at: datetime
    parameters: list[dict[str, Any]]


class TraceabilityOut(Schema):
    unit_id: int
    serial: str
    batch: str
    paint: PaintOut | None
    built_at: datetime
    line: str
    dataset_key: str
    route: list[RouteStep]
    inspections: list[InspectionListItem]
    equipment_events: list[dict[str, Any]]
    provenance: Provenance


# --------------------------------------------------------------------------- investigations


class InvestigationCreate(Schema):
    image_id: int
    baseline_n: int = Field(60, ge=20, le=400)
    alpha: float = Field(0.05, gt=0.0, lt=0.5)


class HypothesisOut(Schema):
    rank: int | None
    factor_type: str
    factor: str
    level: str | None
    station_code: str | None
    status: str
    effect_mm: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    q_value: float | None
    attributable_shift_mm: float | None
    explained_fraction: float | None
    significant: bool
    n_pre: int
    n_post: int
    reason: str | None
    evidence: dict[str, Any]


class InvestigationOut(Schema):
    id: int
    status: str
    method: str
    method_version: str
    created_at: datetime
    duration_ms: float
    trigger: dict[str, Any]
    location: LocationOut
    params: dict[str, Any]
    change_point: dict[str, Any]
    summary: dict[str, Any]
    limitations: list[str]
    hypotheses: list[HypothesisOut]
    evidence: dict[str, Any]
    provenance: Provenance
    verification_runs: list[dict[str, Any]]


class InvestigationListItem(Schema):
    id: int
    status: str
    created_at: datetime
    serial: str
    location: str
    image_id: int
    top_hypothesis: str | None
    top_explained_fraction: float | None


# --------------------------------------------------------------------------- simulation / jobs


class CorrectiveActionCreate(Schema):
    investigation_id: int
    target_code: str = Field(min_length=2, max_length=40)
    kind: Literal["realign_fixture", "recalibrate_tool"] = "realign_fixture"
    n_units: int = Field(120, ge=30, le=400)
    seed: int = Field(1, ge=0, le=2**31 - 1)


class JobOut(Schema):
    id: int
    kind: str
    status: str
    progress: float
    message: str | None
    error: str | None
    attempts: int
    max_attempts: int
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class VerificationOut(Schema):
    id: int
    status: str
    n_units: int
    seed: int
    target_code: str
    kind: str
    investigation_id: int
    job: JobOut | None
    result: dict[str, Any]
    created_at: datetime
    finished_at: datetime | None


# --------------------------------------------------------------------------- pipelines


class PipelineRunOut(Schema):
    id: int
    pipeline: str
    dataset_key: str | None
    source_uri: str | None
    status: str
    started_at: datetime
    finished_at: datetime | None
    duration_s: float | None
    records_in: int
    records_loaded: int
    records_rejected: int
    records_duplicate: int
    records_skipped: int
    error_message: str | None
    retry_of_id: int | None
    metrics: dict[str, Any]
    params: dict[str, Any]


class PipelineRunDetail(PipelineRunOut):
    data_quality: list[dict[str, Any]]
    imports: list[dict[str, Any]]
    error_summary: list[dict[str, Any]]


class PipelineErrorOut(Schema):
    id: int
    file_name: str | None
    row_number: int | None
    field: str | None
    reason: str
    raw: dict[str, Any]


class BenchmarkOut(Schema):
    id: int
    kind: str
    code_version: str
    created_at: datetime
    params: dict[str, Any]
    summary: dict[str, Any]
