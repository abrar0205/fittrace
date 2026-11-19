# Architecture

## Layers

| Layer | Location | Responsibility | Depends on |
|---|---|---|---|
| Scientific core | `packages/fittrace` | Image generation, gap measurement, simulation, SPC/change point/contributor analysis, row validation, benchmarks | NumPy, SciPy, OpenCV, pandas. No web or DB code. |
| Persistence | `apps/api/app/domain/models.py`, `database/migrations`, `database/queries` | Schema, migrations, named analytical SQL | SQLAlchemy, Alembic, PostgreSQL |
| Pipelines | `apps/api/app/pipelines` | `mes_import` (export to tables), `gap_measurement` (images to measurements) | core + persistence |
| Services | `apps/api/app/services` | Inspections, analytics, traceability, investigations, verification, reports, pipelines, jobs, benchmarks | core + persistence |
| HTTP | `apps/api/app/api/routes/v1.py`, `app/schemas/api.py` | Versioned REST, typed contracts independent of the ORM, structured errors | services |
| Worker | `app/worker.py`, `app/services/jobs.py` | Background jobs from a PostgreSQL queue | services |
| Web | `apps/web` | Engineering workbench; typed client generated from OpenAPI | HTTP API only |

## Request and data flow

1. **Generate**: `fittrace.simulation.factory.simulate` produces units, routes, parameters, equipment events and true gaps. `export.write_export` renders the images and writes an MES-style export with checksums and injected data-quality defects. Ground truth goes to `ground_truth/`.
2. **Import**: `run_mes_import` records a `pipeline_runs` row, verifies the manifest checksums, skips unchanged files (`dataset_imports`), validates rows (`fittrace.etl.validation`), and inserts everything in one transaction with `ON CONFLICT DO NOTHING`. Rejects and DQ checks are written in a second transaction so a failure stays visible.
3. **Measure**: `run_measurement_pipeline` processes images that have no pipeline run for the active algorithm version and parameters. It resolves the calibration and the tolerance spec valid at capture time, stores an `inspection_runs` row (success or failure) and a `measurements` row on success, and sets `inspection_images.current_run_id`.
4. **Analyse**: analytics read `measurement_series.sql`, which returns current measurements in production order with each unit's route and parameters as JSON. Investigations use only units built up to the trigger.
5. **Verify**: `POST /simulations/corrective-actions` creates a corrective action, a verification run and a job. The worker claims it, simulates both scenarios, measures them with the vision algorithm, and stores the paired comparison.

## Separation guarantees

- Every business row is scoped to a `dataset` (`kind` is `synthetic` or `real`). Units are unique per dataset, and no query joins across datasets.
- `ground_truth_gaps` and `fault_injections` are read only by evaluation endpoints, benchmarks and the simulator. The measurement path never touches them, and an integration test asserts that the inspection detail contains no true gap.
- Interactive re-runs (`trigger = 'interactive'`) never change `current_run_id`, so analytics only ever see pipeline results.

## Job queue

`jobs` holds the state. A worker claims a job with `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED LIMIT 1)`, reports progress, and on failure re-queues it with a backoff of 5 s × attempts until `max_attempts` is reached. Jobs left `running` by a crashed worker are re-queued when the next worker starts. A queue-depth limit (`FITTRACE_MAX_QUEUED_JOBS`) returns HTTP 429 to protect a public demo.

## Observability

- JSON logs with a request ID (`X-Request-ID` is echoed and included in error bodies), method, path, status and latency for every API request.
- Pipeline and job lifecycles are logged with run and job IDs.
- Health: `/healthz` (process) and `/api/v1/health` (database).
- Pipeline executions, rejects and DQ checks are database records, shown as-is in the Pipelines sheet.
