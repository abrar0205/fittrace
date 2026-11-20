"""Versioned REST API (``/api/v1``). Routes are thin: validation + service call."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import APIError, not_found
from app.domain import models as m
from app.pipelines.measure import resolve_image_path
from app.schemas import api as s
from app.services import analytics, benchmarks, inspections, investigations, pipelines, reports, traceability, verification
from app.services.common import dataset_out, location_dict, resolve_dataset

router = APIRouter(prefix="/api/v1")
DB = Annotated[Session, Depends(get_db)]
PageQ = Annotated[int, Query(ge=1, le=100_000)]
SizeQ = Annotated[int, Query(ge=1, le=500)]
DatasetQ = Annotated[str | None, Query(max_length=80, description="dataset key; defaults to the first synthetic dataset")]


@router.get("/health", response_model=s.Health, tags=["meta"])
def health(db: DB):
    try:
        db.execute(text("select 1"))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    from fittrace import __version__

    return {"status": "ok" if ok else "degraded", "database": "ok" if ok else "unavailable", "version": __version__,
            "demo_readonly": get_settings().demo_readonly}


@router.get("/datasets", response_model=list[s.DatasetOut], tags=["datasets"])
def list_datasets(db: DB):
    return [dataset_out(db, d) for d in db.scalars(select(m.Dataset).order_by(m.Dataset.id))]


@router.get("/locations", response_model=list[s.LocationOut], tags=["datasets"])
def list_locations(db: DB):
    return [location_dict(db, loc) for loc in db.scalars(select(m.MeasurementLocation).order_by(m.MeasurementLocation.code))]


@router.get("/overview", response_model=s.OverviewOut, tags=["analytics"])
def overview(db: DB, dataset: DatasetQ = None):
    try:
        ds = resolve_dataset(db, dataset)
    except APIError as e:
        if e.code != "no_data":
            raise
        ds = None
    return analytics.overview(db, ds)


# --------------------------------------------------------------------------- inspections


@router.get("/inspections", response_model=s.Page[s.InspectionListItem], tags=["inspections"])
def list_inspections(db: DB, dataset: DatasetQ = None, location: Annotated[str | None, Query(max_length=40)] = None,
                     status: Literal["in_tolerance", "out_low", "out_high", "out_of_tolerance", "failed"] | None = None,
                     q: Annotated[str | None, Query(max_length=40)] = None, page: PageQ = 1, page_size: SizeQ = 50,
                     order: Literal["asc", "desc"] = "desc"):
    return inspections.list_inspections(db, resolve_dataset(db, dataset), location, status, q, page, page_size, order)


@router.get("/inspections/{image_id}", response_model=s.InspectionDetail, tags=["inspections"])
def get_inspection(db: DB, image_id: int):
    return inspections.get_inspection(db, image_id)


@router.get("/inspections/{image_id}/image", tags=["inspections"], response_class=FileResponse)
def get_image(db: DB, image_id: int):
    img = db.get(m.InspectionImage, image_id)
    if img is None:
        raise not_found("inspection image", image_id)
    path = resolve_image_path(img.storage_path)
    if not path.is_file():
        raise APIError(410, "image_missing", "image file is no longer available on the server")
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=86400, immutable",
                                                                 "ETag": img.sha256})


@router.post("/inspections/{image_id}/runs", response_model=s.InspectionRunOut, status_code=201, tags=["inspections"])
def rerun_inspection(db: DB, image_id: int, body: s.RerunRequest):
    """Re-run the algorithm interactively. Recorded as an ``interactive`` run; never replaces the pipeline result."""
    return inspections.rerun(db, image_id, body.model_dump())


@router.get("/inspections/{image_id}/ground-truth", response_model=s.GroundTruthComparison, tags=["evaluation"])
def ground_truth(db: DB, image_id: int):
    return inspections.ground_truth(db, image_id)


# --------------------------------------------------------------------------- analytics


@router.get("/analytics/series", response_model=s.SeriesOut, tags=["analytics"])
def series(db: DB, location: Annotated[str, Query(max_length=40)], dataset: DatasetQ = None):
    return analytics.series(db, resolve_dataset(db, dataset), location)


@router.get("/analytics/spc", response_model=s.SpcOut, tags=["analytics"])
def spc(db: DB, location: Annotated[str, Query(max_length=40)], dataset: DatasetQ = None,
        baseline_n: Annotated[int, Query(ge=10, le=1000)] = 100):
    return analytics.spc(db, resolve_dataset(db, dataset), location, baseline_n)


@router.get("/analytics/stations/{station}", response_model=s.StationComparisonOut, tags=["analytics"])
def station_comparison(db: DB, station: str, location: Annotated[str, Query(max_length=40)], dataset: DatasetQ = None):
    return analytics.station_comparison(db, resolve_dataset(db, dataset), location, station)


# --------------------------------------------------------------------------- traceability


@router.get("/units/{unit_id}/traceability", response_model=s.TraceabilityOut, tags=["traceability"])
def unit_traceability(db: DB, unit_id: int, window_h: Annotated[int, Query(ge=1, le=720)] = 48):
    return traceability.unit_trace(db, unit_id=unit_id, event_window_h=window_h)


@router.get("/traceability", response_model=s.TraceabilityOut, tags=["traceability"])
def traceability_by_serial(db: DB, serial: Annotated[str, Query(min_length=3, max_length=40)], dataset: DatasetQ = None,
                           window_h: Annotated[int, Query(ge=1, le=720)] = 48):
    return traceability.unit_trace(db, serial=serial, dataset_id=resolve_dataset(db, dataset).id, event_window_h=window_h)


# --------------------------------------------------------------------------- investigations


@router.post("/investigations", response_model=s.InvestigationOut, status_code=201, tags=["investigations"])
def create_investigation(db: DB, body: s.InvestigationCreate):
    inv = investigations.create_investigation(db, body.image_id, body.baseline_n, body.alpha)
    return investigations.investigation_out(db, inv)


@router.get("/investigations", response_model=s.Page[s.InvestigationListItem], tags=["investigations"])
def list_investigations(db: DB, page: PageQ = 1, page_size: SizeQ = 20):
    return investigations.list_investigations(db, page, page_size)


@router.get("/investigations/{inv_id}", response_model=s.InvestigationOut, tags=["investigations"])
def get_investigation(db: DB, inv_id: int):
    return investigations.get_investigation(db, inv_id)


@router.get("/reports/investigations/{inv_id}.json", tags=["reports"])
def report_json(db: DB, inv_id: int):
    return reports.investigation_report(db, inv_id)


@router.get("/reports/investigations/{inv_id}.md", response_class=PlainTextResponse, tags=["reports"])
def report_md(db: DB, inv_id: int):
    return PlainTextResponse(reports.investigation_markdown(db, inv_id), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="fittrace-investigation-{inv_id}.md"'})


# --------------------------------------------------------------------------- simulations & jobs


@router.post("/simulations/corrective-actions", response_model=s.VerificationOut, status_code=202, tags=["simulations"])
def create_corrective_action(db: DB, body: s.CorrectiveActionCreate):
    return verification.create_verification(db, body.investigation_id, body.target_code, body.kind, body.n_units, body.seed)


@router.get("/simulations/verifications/{vr_id}", response_model=s.VerificationOut, tags=["simulations"])
def get_verification(db: DB, vr_id: int):
    return verification.get_verification(db, vr_id)


@router.get("/jobs/{job_id}", response_model=s.JobOut, tags=["jobs"])
def get_job(db: DB, job_id: int):
    j = db.get(m.Job, job_id)
    if j is None:
        raise not_found("job", job_id)
    return j


# --------------------------------------------------------------------------- pipelines


@router.get("/pipelines/runs", response_model=s.Page[s.PipelineRunOut], tags=["pipelines"])
def list_pipeline_runs(db: DB, pipeline: Annotated[str | None, Query(max_length=60)] = None,
                       status: Literal["running", "succeeded", "failed", "skipped"] | None = None,
                       page: PageQ = 1, page_size: SizeQ = 50):
    return pipelines.list_runs(db, pipeline, status, page, page_size)


@router.get("/pipelines/runs/{run_id}", response_model=s.PipelineRunDetail, tags=["pipelines"])
def pipeline_run(db: DB, run_id: int):
    return pipelines.run_detail(db, run_id)


@router.get("/pipelines/runs/{run_id}/errors", response_model=s.Page[s.PipelineErrorOut], tags=["pipelines"])
def pipeline_errors(db: DB, run_id: int, page: PageQ = 1, page_size: SizeQ = 100):
    return pipelines.run_errors(db, run_id, page, page_size)


@router.post("/pipelines/runs/{run_id}/retry", response_model=s.JobOut, status_code=202, tags=["pipelines"])
def retry_pipeline_run(db: DB, run_id: int):
    if get_settings().demo_readonly:
        raise APIError(403, "demo_readonly", "re-processing is disabled in the public read-only demo")
    return pipelines.retry(db, run_id)


# --------------------------------------------------------------------------- evaluation


@router.get("/evaluation/{kind}", response_model=s.BenchmarkOut, tags=["evaluation"])
def benchmark(db: DB, kind: Literal["vision", "investigation"]):
    return benchmarks.latest(db, kind)


@router.get("/evaluation/vision/cases/{index}/image", tags=["evaluation"])
def benchmark_case_image(db: DB, index: int):
    """Re-render a benchmark case deterministically from its stored scene parameters."""
    from fastapi.responses import Response

    from fittrace.simulation.geometry import SceneParams, encode_png, render_panel_gap

    b = benchmarks.latest(db, "vision")
    cases = b.summary.get("cases", [])
    if not 0 <= index < len(cases) or not cases[index].get("scene"):
        raise not_found("benchmark case", index)
    img, _ = render_panel_gap(SceneParams(**cases[index]["scene"]))
    return Response(encode_png(img), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
