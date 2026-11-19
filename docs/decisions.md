# Technical decisions

## Phase 0: evidence (checked 19 Nov 2026)

- **Industry context.** The public posting "Senior Quality Dimensional Data Scientist, Gigafactory Berlin-Brandenburg" (Req. 284859) loaded only its header (title, location, job type) in the research tool. Its description was read via a third-party job-board mirror, which describes end-of-line gap-and-flush scanning and correlating deviations with upstream process traces. That was **not verified on the official page**. It is used only as context for which capabilities matter. FitTrace does not reproduce any company's software, data or defects.
- **Datasets:** see [datasets.md](datasets.md). In short, synthetic data is the primary track, Carparts-Seg's licence is ambiguous, the NIST download was blocked, and Bosch needs a sign-in.
- **Environment:** Python 3.13, Node 22, PostgreSQL 16 and Chrome were available. There was no Docker daemon, and outbound HTTP was limited to package registries and GitHub.

## Decisions

| # | Decision | Alternatives | Why |
|---|---|---|---|
| D1 | Modular monolith (FastAPI) plus a separate worker process | Microservices | One domain, one database, a small team. The boundaries are package boundaries: the scientific core has no web or DB imports. |
| D2 | PostgreSQL-backed job queue (`SKIP LOCKED`) | Redis + RQ, Celery | Every job reads and writes Postgres anyway. It saves a service, job state is transactional with results, and it costs nothing on a student budget. The trade-off is lower throughput, which is irrelevant at this volume. |
| D3 | Scan-line plus robust line fit instead of Hough or learned models | Canny + Hough, CNN regression | Sub-pixel accuracy, explicit failure modes, diagnosable overlays, and no training data needed. Deep learning would add claims the data cannot support. |
| D4 | Hem shading built into the generator | Ideal step edges | Ideal edges give sub-micron errors that would be misleading. Modelling shading produces a realistic, explainable bias that the benchmark can show. |
| D5 | Ground truth in separate tables and endpoints | Columns on `inspection_images` | Makes leakage into measurement structurally impossible and testable. |
| D6 | `current_run_id` pointer; interactive re-runs never change it | Latest run wins | Analytics stay reproducible while engineers experiment with parameters. |
| D7 | Named SQL files for analytics | ORM-built queries everywhere | The analytical SQL is reviewable as SQL. The ORM is used for transactional writes. |
| D8 | File checksums plus natural-key `ON CONFLICT DO NOTHING` | Truncate and reload | Gives both file-level and row-level idempotency and supports incremental deliveries. |
| D9 | One atomic transaction per import run, with errors written separately | Per-file commits | A failed run leaves no partial business data, but its errors remain auditable. |
| D10 | Difference-in-differences attribution | Feature importance from a model, raw correlation | Each number has a plain meaning ("how much more this fixture changed than the rest") and comes with CIs and multiple-testing control. |
| D11 | Paired counterfactual verification | Comparing against historical post-change units | Identical random draws isolate the action's effect within the simulation, and a wrong target visibly shows no effect. |
| D12 | One container serving the API, worker thread and built UI | Separate static host + API + worker | Cheapest viable public deployment (one web service plus managed Postgres). Compose still runs the worker separately. |
| D13 | Deterministic seeding on start | Persistent disk for images | Free hosts have ephemeral disks. Re-seeding recreates byte-identical images, and the import skips unchanged files. |
| D14 | OpenAPI-generated TypeScript types, checked in CI | Hand-written types | The contracts cannot drift silently. |
| D15 | Drafting-sheet visual language (title blocks, dimension lines, caliper gauge) | Generic admin dashboard | The UI should feel like a metrology tool, and the title block carries provenance on every sheet. |
