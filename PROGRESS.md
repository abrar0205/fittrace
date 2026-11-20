# Implementation status and verification report

Last updated: 20 Nov 2026 (release 1.1). Everything below was executed in the development environment (Python 3.13, PostgreSQL 16.15, Node 22, Chrome) unless it is marked otherwise.

## Release 1.1: realistic imagery and workbench

| Item | Evidence |
|---|---|
| Colour image generator 2.0 | Seven invented paint codes, clear-coat reflection, orange peel, flake, dust, flange and pillar gap interiors, exposure recipe that keeps dark paints dark without clipping red. Unit tests: BGR determinism and every paint × gap style measured with a bias between 10 and 35 µm |
| S40 paint shop | Booths PB-401/402 with film build and booth temperature; film build enters the gap model; new factors are included in investigations. Migration 0002 (paint codes, unit paint, booth equipment) tested upgrade → downgrade → upgrade on a populated database; `alembic check` clean |
| Latent schema fix | `fk_image_current_run` was declared in the model but never created by migration 0001 (Alembic does not emit `use_alter` foreign keys inside `create_table`). Migration 0002 creates it |
| Algorithm 1.1.0 | Noise-adaptive edge threshold; the 3 black-paint images that failed under 1.0 in the integration dataset now measure with all rows valid |
| Workbench | Imaging stage with heads-up chips and a scale bar, list thumbnails with paint, location history, unit route card, edge-threshold controls in re-runs, Ctrl K command palette. Checked in Chrome at 1440 and 390 px; no horizontal page scroll at 390 px on any sheet |

## Implemented and verified

| Item | Evidence |
|---|---|
| Calibrated synthetic image generator (deterministic) | Unit tests: identical bytes for identical seeds, exact ground-truth geometry, lossless PNG round trip |
| Gap algorithm with refusal on failure | 20 unit tests: known gaps within 3 µm on ideal edges at 3 angles, uncalibrated returns px only, invalid calibration, blank image, bad shapes and heavy occlusion all fail with no value, overlay equals algorithm state |
| Vision benchmark | Generator 2.0 (colour, 7 paints, reflections) and algorithm 1.1.0: 1,736 images including the paint and reflection sweeps; bias 23.7 µm, RMSE 23.9 µm, no failures at nominal conditions or on any paint. Stored and shown on the Method sheet |
| Manufacturing simulator with fault injection | Unit test: deterministic, and the corrected scenario differs by exactly the injected offset on exactly the faulted units |
| PostgreSQL schema and reversible migrations | The integration session runs upgrade, downgrade to base, then upgrade again on every run |
| ETL import | Integration tests: valid load; rejects match injected orphan defects 1:1; exact duplicates counted not loaded; file-level and row-level idempotency; checksum failure and quality gate roll back with no data; rejects stay auditable |
| Measurement pipeline | 1,120 colour demo images measured, 0 failures; resumable (second run reports `skipped`); bias against ground truth asserted between 10 and 40 µm |
| REST API (28 operations, OpenAPI) | 12 API integration tests: pagination, filters, structured 404/422/409, unit association, PNG serving, interactive re-runs not replacing pipeline results, ground truth isolation, traceability, SPC, station comparison, pipeline monitor, reports |
| Investigation | Recovers the demo fault: FX-202 ranked first, q < 0.0001, change point at SIM-00266 against a true start of SIM-00265; idempotent for the same trigger. The two earliest out-of-tolerance triggers correctly report no sustained shift or no significant contributor |
| Contributor-recovery benchmark | 60 faulted + 20 fault-free histories; reproduced exactly from the CLI |
| Corrective-action job | Integration test of the full queue lifecycle; live run: FX-202 −0.147 mm (CI −0.183 to −0.111), OOT 9.2% to 0%; FX-203 no effect |
| Responsive layout | Checked at 1920, 1440, 1280, 1024 and 390 px. The rail collapses to icons at 1100 px or below and becomes a sticky top bar at 760 px or below; the workbench places the result above the image below 1280 px. A script confirms that none of the 7 sheets scrolls horizontally at 390 px |
| Frontend: 7 sheets | Inspected in Chrome at 1440 and 1920 px; scan reveal, loupe, row profile, chart click-through and verification polling exercised; layout defects found in review were fixed (viewer overflow, scaled SVG text, label collisions, table overflow) |
| Frontend checks | ESLint and `tsc` clean; 14 Vitest tests; 2 Playwright e2e tests (plus 1 snapshot-only) pass against both the dev server and the production build served by the API |
| Lint | `ruff check .` clean |
| GitHub Pages snapshot | `prepare-snapshot` produced 25 investigations and 24 verification runs locally, and `export-snapshot` wrote 4,068 files (103 MB). The built site, served like Pages under `/fittrace/` with a 404 fallback, passes 3 Playwright tests (deep links, provenance, read-only actions, line map). An integration test asserts that the exported files equal the API responses |
| Determinism fix | `test_snapshot` intermittently found the overview's hourly aggregates differing between two identical requests (about 1 in 4 full-suite runs). The root cause is not proven; the most likely one is float summation order changing with the query plan on a freshly loaded test database. The trend and station aggregates are now computed in exact `numeric`, and every ordered query has a unique tie-breaker. 30 consecutive full-suite runs have passed since |
| GitHub Actions | Passed on PR #1: `python` (ruff, 62 tests on a PostgreSQL 16 service, OpenAPI drift check), `web` (type drift, lint, tsc, Vitest, build), `e2e` (fresh migrate + seed, Playwright against the API-served build) |

## Not done or not verified

| Item | Status |
|---|---|
| Docker image and `docker compose` | Written, **not built**: no Docker daemon in the environment |
| Interactive (API) deployment | Not deployed: needs a host for the API and database. The public demo is the static GitHub Pages snapshot; see `docs/deployment.md` |
| NIST box-assembly ingestion | Blocked: download refused by the environment's network policy; contents not inspected, nothing assumed |
| Carparts-Seg | Not integrated: licence ambiguous (AGPL-3.0 vs CC BY 4.0) |
| Bosch benchmark | Not attempted: needs a Kaggle sign-in |
| Flush measurement | Out of scope without calibrated depth data |
| Hem-shading bias correction | Not implemented; documented (it also varies by 2.5 µm across paints) |
| Real gap imagery | No calibrated public gap dataset exists. Carparts-Seg was downloaded and inspected but is not published here until its licence is confirmed |

## Open defects and next steps

1. Run the Docker build and compose stack on a machine with Docker; fix anything it surfaces.
2. Deploy (managed Postgres + one Docker web service, `FITTRACE_DEMO_READONLY=true`) and run the e2e suite against the public URL.
3. Download the NIST `mtc.zip` locally, inspect it, and add a separate `real` dataset track.
4. Add a reference-artefact bias correction and a GUM-style uncertainty budget.
5. Add multiple change points or a self-starting CUSUM to reduce the 50% short-baseline false-alarm rate.
6. Bundle size: Plotly is lazy-loaded (451 kB gzip); a custom-trace build could shrink it further.
