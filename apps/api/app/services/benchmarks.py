from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.errors import not_found
from app.domain import models as m
from fittrace import __version__
from fittrace.evaluation import investigation_bench, vision_bench
from fittrace.vision.gap import ALGORITHM_NAME, ALGORITHM_VERSION


def run_vision_benchmark(per_condition: int = 24, nominal_n: int = 200) -> dict:
    res = vision_bench.run_vision_benchmark(per_condition=per_condition, nominal_n=nominal_n)
    with session_scope() as db:
        db.add(m.BenchmarkResult(kind="vision", code_version=f"{ALGORITHM_NAME}@{ALGORITHM_VERSION}",
                                 params=res["params"], summary=res))
    return res


def latest_vision_stats(db: Session) -> tuple[float, float]:
    b = db.scalar(select(m.BenchmarkResult).where(m.BenchmarkResult.kind == "vision")
                  .order_by(m.BenchmarkResult.created_at.desc(), m.BenchmarkResult.id.desc()).limit(1))
    if b is None:
        return 0.0235, 0.003
    o = b.summary["overall"]
    bias = (o["bias_um"] or 0) / 1000
    rmse = (o["rmse_um"] or 0) / 1000
    sigma = max(1e-4, (max(rmse**2 - bias**2, 0)) ** 0.5)
    return bias, sigma


def run_investigation_benchmark(n_runs: int = 40, n_null: int | None = None) -> dict:
    with session_scope() as db:
        bias, sigma = latest_vision_stats(db)
    res = investigation_bench.run_investigation_benchmark(n_runs=n_runs, n_null=n_null, meas_bias_mm=bias,
                                                          meas_sigma_mm=sigma)
    consistency = investigation_bench.run_investigation_benchmark(n_runs=3, n_null=0, mode="full_pipeline",
                                                                  seed=res["params"]["seed"], n_perm=199)
    res["full_pipeline_consistency"] = {"overall": consistency["overall"],
                                        "runs": [{k: r[k] for k in ("fault_class", "target", "alarm_index")} |
                                                 {"top_full_history": r["full_history"]["top_hypothesis"]}
                                                 for r in consistency["runs"]]}
    with session_scope() as db:
        db.add(m.BenchmarkResult(kind="investigation", code_version=f"fittrace@{__version__}", params=res["params"],
                                 summary=res))
    return res


def latest(db: Session, kind: str) -> m.BenchmarkResult:
    b = db.scalar(select(m.BenchmarkResult).where(m.BenchmarkResult.kind == kind)
                  .order_by(m.BenchmarkResult.created_at.desc(), m.BenchmarkResult.id.desc()).limit(1))
    if b is None:
        raise not_found("benchmark result of kind", kind)
    return b
