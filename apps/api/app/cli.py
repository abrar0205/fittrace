"""FitTrace command-line interface.

    python -m app.cli seed-demo            # generate, import, measure, benchmark (idempotent)
    python -m app.cli generate --key K     # write a simulated MES export
    python -m app.cli import --dir D --key K
    python -m app.cli measure --key K
    python -m app.cli benchmark-vision [--per-condition N]
    python -m app.cli benchmark-investigation [--runs N] [--null N]
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_scope
from app.core.logging import configure_logging
from app.domain import models as m
from app.pipelines.measure import run_measurement_pipeline
from app.pipelines.mes_import import run_mes_import
from fittrace.simulation.export import write_export
from fittrace.simulation.factory import SimConfig, default_fault, simulate

logger = logging.getLogger("fittrace.cli")

DEMO_KEY = "sim-biw-demo-v1"
DEMO_TOTAL_UNITS = 560
DEMO_FIRST_INCREMENT = 480


def demo_simulation():
    cfg = SimConfig(n_units=DEMO_TOTAL_UNITS, faults=[default_fault(DEMO_FIRST_INCREMENT)])
    return simulate(cfg)


def cmd_generate(args) -> None:
    out = Path(args.out or get_settings().data_dir / "raw" / args.key)
    res = simulate(SimConfig(n_units=args.units, seed=args.seed, faults=[default_fault(args.units)]))
    manifest = write_export(res, out, args.key, dq_defect_rate=args.dq_rate)
    print(json.dumps({"out": str(out), "units": manifest["n_units"], "injected_defects": manifest["injected_defects"]}))


def seed_demo(with_benchmarks: bool = True, bench_per_condition: int = 24, bench_runs: int = 60, bench_null: int = 20) -> None:
    s = get_settings()
    raw = s.data_dir / "raw"
    with session_scope() as db:
        existing = db.scalar(select(m.Dataset).where(m.Dataset.key == DEMO_KEY))
        has_runs = existing is not None and db.scalar(select(m.PipelineRun.id).where(m.PipelineRun.dataset_id == existing.id)
                                                      .limit(1)) is not None
    res = demo_simulation()
    inc1, inc2 = raw / f"{DEMO_KEY}-inc001", raw / f"{DEMO_KEY}-inc002"
    if not (inc1 / "manifest.json").is_file():
        write_export(res, inc1, DEMO_KEY, unit_range=(0, DEMO_FIRST_INCREMENT))
    if not (inc2 / "manifest.json").is_file():
        write_export(res, inc2, DEMO_KEY, unit_range=(DEMO_FIRST_INCREMENT, DEMO_TOTAL_UNITS), dq_seed=11)
    if has_runs:
        print("demo dataset already seeded; re-running pipelines is idempotent")
    # 1) baseline import, 2) identical re-delivery (must be skipped), 3) a corrupted delivery
    #    (truncated file -> checksum mismatch -> run fails, nothing loaded), 4) the next increment.
    run_mes_import(inc1, DEMO_KEY, "Simulated BIW line - gap inspection demo")
    run_mes_import(inc1, DEMO_KEY)
    corrupt = raw / f"{DEMO_KEY}-inc002-corrupt"
    if not corrupt.exists():
        shutil.copytree(inc2, corrupt, ignore=shutil.ignore_patterns("images"))
        (corrupt / "images").symlink_to(inc2 / "images", target_is_directory=True)
        p = corrupt / "process_parameters.csv"
        p.write_text("\n".join(p.read_text().splitlines()[:-37]) + "\n")
    if not has_runs:
        run_mes_import(corrupt, DEMO_KEY)
    run_mes_import(inc2, DEMO_KEY)
    run_measurement_pipeline(DEMO_KEY)
    if with_benchmarks:
        from app.services.benchmarks import run_investigation_benchmark, run_vision_benchmark

        with session_scope() as db:
            have = {k for (k,) in db.execute(select(m.BenchmarkResult.kind))}
        if "vision" not in have:
            run_vision_benchmark(per_condition=bench_per_condition)
        if "investigation" not in have:
            run_investigation_benchmark(n_runs=bench_runs, n_null=bench_null)


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    ap = argparse.ArgumentParser(prog="fittrace")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate")
    g.add_argument("--key", required=True)
    g.add_argument("--units", type=int, default=480)
    g.add_argument("--seed", type=int, default=20260214)
    g.add_argument("--dq-rate", type=float, default=0.01)
    g.add_argument("--out")
    i = sub.add_parser("import")
    i.add_argument("--dir", required=True)
    i.add_argument("--key", required=True)
    me = sub.add_parser("measure")
    me.add_argument("--key", required=True)
    sd = sub.add_parser("seed-demo")
    sd.add_argument("--no-benchmarks", action="store_true")
    sd.add_argument("--bench-per-condition", type=int, default=24)
    sd.add_argument("--bench-runs", type=int, default=60)
    bv = sub.add_parser("benchmark-vision")
    bv.add_argument("--per-condition", type=int, default=24)
    bi = sub.add_parser("benchmark-investigation")
    bi.add_argument("--runs", type=int, default=60)
    bi.add_argument("--null", type=int, default=20)
    args = ap.parse_args()
    if args.cmd == "generate":
        cmd_generate(args)
    elif args.cmd == "import":
        print(run_mes_import(args.dir, args.key))
    elif args.cmd == "measure":
        print(run_measurement_pipeline(args.key))
    elif args.cmd == "seed-demo":
        seed_demo(not args.no_benchmarks, args.bench_per_condition, args.bench_runs)
    elif args.cmd == "benchmark-vision":
        from app.services.benchmarks import run_vision_benchmark

        print(json.dumps(run_vision_benchmark(per_condition=args.per_condition)["overall"], indent=2))
    elif args.cmd == "benchmark-investigation":
        from app.services.benchmarks import run_investigation_benchmark

        print(json.dumps(run_investigation_benchmark(n_runs=args.runs, n_null=args.null)["overall"], indent=2))


if __name__ == "__main__":
    main()
