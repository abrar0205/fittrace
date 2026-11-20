# FitTrace

**Automotive dimensional quality engineering platform.** FitTrace measures panel gaps in calibrated inspection images, links each measurement to the unit's (simulated) manufacturing history, and investigates out-of-tolerance results down to statistically supported, explicitly hedged process contributors. It also verifies a corrective action in a paired simulation.

It is an independent portfolio project. All production data is **simulated** and all inspection images are **procedurally generated with known calibration**. It has no affiliation with, and no data from, any manufacturer.

**Live demo: https://abrar0205.github.io/fittrace/**

The demo is a static snapshot published by GitHub Actions. On every push to `main`, the [pages workflow](.github/workflows/pages.yml) does the following on a fresh PostgreSQL:
1. seeds and imports the simulated line;
2. measures all 1,120 images;
3. runs both benchmarks;
4. investigates every out-of-tolerance inspection;
5. runs the corrective-action simulations;
6. exports the API's responses as files;
7. tests the built site in a browser;
8. publishes it.

Every number on the site is computed in that run. The viewer, loupe, scan replay, profiles, charts and navigation all work on the snapshot. Actions that need a server (re-running a measurement with new parameters, starting new verifications, retrying pipelines) are disabled there and work when you run the full stack.

![Inspection workbench: calibrated gap image with the algorithm's edge points, fitted edges, dimension, loupe and row intensity profile](docs/images/workbench.png)

## The problem

Finding an abnormal gap is the start of the work, not the end. An engineer also needs to know where it was measured, by how much it is off, whether it has happened before, which upstream station, fixture or tool it is associated with, what evidence supports that, whether a fix worked, and whether the analysis can be reproduced. FitTrace connects those questions in one workflow:

```
calibrated image ──► gap algorithm ──► measurement + tolerance ──► PostgreSQL
        ▲                                                           │
        │                       unit route, parameters, events ◄────┤ (ETL from MES-style exports)
  simulator (known faults)                                          ▼
        ▲                       change point ► ranked contributors ► report
        └──── corrective-action simulation ◄── verification (paired, measured by the same algorithm)
```

## What it does (all verified, see [PROGRESS.md](PROGRESS.md))

| Area | Implementation |
|---|---|
| Synthetic data | Calibrated panel-gap images (area-sampled edges, PSF blur, hem shading, illumination, noise, occlusion) and a body-in-white line simulator with an explicit gap model and injectable faults (fixture shift, tool calibration drift). Deterministic seeds. |
| Measurement | OpenCV scan-line algorithm: sub-pixel edges (parabolic peak), robust line fits (MAD rejection), parallelism check, perpendicular gap, mm via calibration valid at capture time. Refuses to report a value when prerequisites fail. |
| ETL | MES-style CSV exports to PostgreSQL. Atomic per run, idempotent by file checksum and natural keys, incremental, with a reject-rate quality gate, audited rejected rows and data-quality checks. Failed runs can be retried. |
| Database | 28 tables, Alembic migrations (reversible, tested), FK/unique/check constraints, query-driven indexes, ground truth in separate tables. Analytical SQL in `database/queries/*.sql`. |
| Analytics | I-MR charts with Phase I baseline limits and applicability checks (n, lag-1 autocorrelation, normality); spec limits kept separate from control limits; station comparison. |
| Investigation | Permutation-tested mean-shift change point, then difference-in-differences per equipment level and slope per parameter (OLS, HC3), Benjamini-Hochberg, transparent "share of shift explained" ranking, aliasing detection, generated limitations, JSON/Markdown reports with a content hash. |
| Verification | Background job continues the simulated line twice with identical random draws (with and without the action), renders and measures both, and reports the paired change, CI, Hedges g and the OOT change with Fisher's exact test. |
| Jobs | PostgreSQL queue (`FOR UPDATE SKIP LOCKED`), retries with backoff, stale-job recovery; separate worker process or in-process thread. |
| UI | React + TypeScript workbench (described below). |

## Screens

The UI follows the conventions of an engineering drawing rather than a dashboard. Each sheet ends in a **title block** that carries its provenance (dataset, simulated source, algorithm or method version, render time). Measurements are drawn as **ISO-style dimension lines**, and colour has fixed jobs: teal means computed by the algorithm, amber means out of tolerance, red means a processing error.

| | |
|---|---|
| ![Overview](docs/images/overview.png) **Overview**: a line map of every fixture and nutrunner against the specification window, a four-step walkthrough of one deviation, distributions, hourly trend, pipeline health, provenance. | ![Investigation](docs/images/investigation.png) **Investigation**: deviation history with the change point, ranked contributors with effect CIs, difference-in-differences evidence, events near the change, limitations, verification. |
| ![Analytics](docs/images/analytics.png) **Analytics**: I-MR chart (baseline-estimated limits, Western Electric R1/R2/R4), with spec and control limits drawn differently; station comparison. | ![Traceability](docs/images/traceability.png) **Traceability**: routing sheet of stations, equipment, parameters and timings, linked inspections, equipment events before the build. |
| ![Pipelines](docs/images/pipelines.png) **Pipelines**: every recorded execution with record flow, failure reason, retry, rejected rows, data-quality checks. | ![Evaluation](docs/images/evaluation.png) **Method and evaluation**: benchmark sweeps showing where the algorithm holds and breaks, failure gallery re-rendered from stored parameters, recovery benchmark. |

Interaction effects are driven by data, not decoration. The **scan-line reveal** replays the algorithm's row sampling order. The **loupe** magnifies the real pixels with the detected sub-pixel edges overlaid. The **row profile** plots the hovered row's grey values and gradient. The **caliper-style tolerance gauge** has go/no-go jaws at the specification limits. Clicking a control-chart point opens its inspection. Interactive re-runs with different parameters are stored for audit but never replace the pipeline result. Reduced-motion preferences are respected.

## Architecture

```mermaid
flowchart LR
  subgraph core["packages/fittrace (no web or DB code)"]
    SIM[simulation<br/>geometry + factory + export]
    VIS[vision<br/>gap + tolerance]
    ANA[analytics<br/>SPC, change point, contributors]
    VAL[etl.validation]
    EVA[evaluation<br/>benchmarks]
  end
  subgraph api["apps/api (FastAPI)"]
    R[/api/v1 routes/] --> SVC[services]
    SVC --> SQL[(named SQL)]
    PIPE[pipelines<br/>mes_import, gap_measurement]
    JOBS[job queue + worker]
  end
  WEB[apps/web<br/>React + TS + Plotly] -->|typed client from OpenAPI| R
  SVC & PIPE & JOBS --> PG[(PostgreSQL)]
  PIPE --> VIS & VAL
  SVC --> ANA
  JOBS --> SIM & VIS
  SIM -->|MES-style export| PIPE
```

More detail is in [docs/architecture.md](docs/architecture.md). The decisions and their trade-offs (Postgres-backed queue over Redis/RQ, a single image for API, worker and UI, named SQL files, deterministic re-seeding) are in [docs/decisions.md](docs/decisions.md).

**Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL 16, NumPy, SciPy, OpenCV, pandas, pytest; React 19, TypeScript, Vite, TanStack Query, Plotly (lazy-loaded), Vitest, Playwright; GitHub Actions; Docker.

## Results (stored benchmark runs, reproducible)

**Gap measurement**, 200 images from the nominal operating distribution ([details](docs/evaluation.md)):

| Bias | RMSE | p95 abs. error | Failure rate | Tolerance calls correct | Latency p50 / p95 |
|---:|---:|---:|---:|---:|---:|
| +23.5 µm | 23.7 µm | 27.7 µm | 0.0% | 98.5% | 17.3 / 25.2 ms |

The bias is systematic and physically motivated. With simulated hem shading (0.06 mm edge roll-off), the intensity edge lies outside the true silhouette. On ideal step edges the error is below 1 µm, which would not be a credible number to quote. A ±1% calibration error moves the result by about 40 µm at a 4 mm gap. At 0.01 mm/px the gap no longer fits the field of view, so 54% of measurements fail, and with 70% or more of the rows occluded the algorithm declines to measure.

**Contributor recovery**, 60 simulated histories with random injected faults plus 20 fault-free histories:

| Fault class | Top-1 at CUSUM alarm | Top-1 at alarm + 60 units | Top-1, full history |
|---|---:|---:|---:|
| S20 side-aperture fixture shift | 0% | 75% | 100% |
| S30 nutrunner torque calibration drift | 15% | 65% | 100% |
| S10 underbody fixture shift (weak coupling) | 25% | 55% | 100% |

On fault-free histories, the CUSUM alarm (h = 6, limits from 60 units) fires in **55%** of runs, because a short baseline misestimates the process. The investigation attributes a significant contributor in **5%**. Full-history recovery is high because the simulated faults are recorded factors of meaningful size; [docs/limitations.md](docs/limitations.md) explains why that does not transfer to a real plant.

## Run it

Requirements: Python 3.11+, Node 22, PostgreSQL 16.

```bash
# 1. backend
pip install -e packages/fittrace -e "apps/api[dev]"
createdb fittrace && createdb fittrace_test          # or use docker compose up db
export FITTRACE_DATABASE_URL=postgresql+psycopg://USER:PASS@localhost:5432/fittrace
cd apps/api
alembic upgrade head
python -m app.cli seed-demo          # generate, import (4 runs incl. a corrupt delivery), measure, benchmark (~3 min)
FITTRACE_RUN_WORKER_IN_PROCESS=true uvicorn app.main:app --port 8000

# 2. frontend (dev server proxies /api to :8000)
cd apps/web && npm ci && npm run dev  # http://localhost:5173
```

To reproduce the public snapshot locally: `python -m app.cli prepare-snapshot && python -m app.cli export-snapshot --out ../../site/fittrace/snapshot`, then build the web app with `VITE_SNAPSHOT=1 VITE_BASE=/fittrace/`.

Or with Docker: `docker compose up --build`, then open http://localhost:8000. The API serves the built UI, a worker container processes jobs, and the API seeds on first start. The compose file is written but could not be run in the build environment (no Docker daemon); see [PROGRESS.md](PROGRESS.md).

API docs are at `/docs` (OpenAPI). The TypeScript client types are generated from `docs/openapi.json` (`npm run gen:api`), and CI fails if either side drifts.

## Tests

```bash
pytest                                   # 63 tests: unit + integration against real PostgreSQL (FITTRACE_TEST_DATABASE_URL)
ruff check .
cd apps/web && npm run lint && npm run typecheck && npm test   # 14 Vitest tests
CHROME_PATH=/usr/bin/google-chrome npx playwright test        # e2e against a running, seeded stack (E2E_SNAPSHOT=1 for the static build)
```

The integration tests cover reversible migrations, idempotent re-import (file-level and row-level), rollback on checksum failure and on the quality gate, auditable rejects matching the injected defects, measurement accuracy against ground truth, the API contracts (pagination, structured errors, unit associations, ground truth isolation), investigation storage and idempotency, and the full corrective-action job lifecycle.

## Documentation

[architecture](docs/architecture.md), [datasets](docs/datasets.md), [methodology](docs/methodology.md), [evaluation](docs/evaluation.md), [limitations](docs/limitations.md), [decisions](docs/decisions.md), [deployment](docs/deployment.md), [portfolio summary](docs/portfolio.md), [verification report](PROGRESS.md).

## Known limitations (short version)

Flush is not measured, because it needs calibrated depth data. The images are synthetic and single-view. Investigation results are associations among recorded factors. The public datasets (Carparts-Seg, NIST, Bosch) are documented but not integrated, for the licence and access reasons given in [docs/datasets.md](docs/datasets.md). The full list is in [docs/limitations.md](docs/limitations.md).

## License

MIT, see [LICENSE](LICENSE).
