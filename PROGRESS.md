# Implementation status and verification report

Last updated: 19 Nov 2026. Everything below was executed in the development environment (Python 3.13, PostgreSQL 16.15, Node 22, Chrome) unless it is marked otherwise.

## Implemented and verified

| Item | Evidence |
|---|---|
| Calibrated synthetic image generator (deterministic) | Unit tests: identical bytes for identical seeds, exact ground-truth geometry, lossless PNG round trip |
| Gap algorithm with refusal on failure | 20 unit tests: known gaps within 3 µm on ideal edges at 3 angles, uncalibrated returns px only, invalid calibration, blank image, bad shapes and heavy occlusion all fail with no value, overlay equals algorithm state |
| Vision benchmark | 1,388 images, stored and shown on the Method sheet; re-run reproduced identical numbers (bias 23.514 µm, RMSE 23.724 µm) |
| Manufacturing simulator with fault injection | Unit test: deterministic, and the corrected scenario differs by exactly the injected offset on exactly the faulted units |
| PostgreSQL schema and reversible migrations | The integration session runs upgrade, downgrade to base, then upgrade again on every run |
| ETL import | Integration tests: valid load; rejects match injected orphan defects 1:1; exact duplicates counted not loaded; file-level and row-level idempotency; checksum failure and quality gate roll back with no data; rejects stay auditable |
| Measurement pipeline | 1,120 demo images measured, 0 failures, 19 s; resumable (second run reports `skipped`); bias against ground truth asserted between 10 and 40 µm |
| REST API (28 operations, OpenAPI) | 12 API integration tests: pagination, filters, structured 404/422/409, unit association, PNG serving, interactive re-runs not replacing pipeline results, ground truth isolation, traceability, SPC, station comparison, pipeline monitor, reports |
| Investigation | Recovers the demo fault: FX-202 ranked first, q < 0.0001, change point at SIM-00266 against a true start of SIM-00265; idempotent for the same trigger |
| Contributor-recovery benchmark | 60 faulted + 20 fault-free histories; reproduced exactly from the CLI |
| Corrective-action job | Integration test of the full queue lifecycle; live run: FX-202 −0.147 mm (CI −0.183 to −0.111), OOT 9.2% to 0%; FX-201 no effect |
| Frontend: 7 sheets | Inspected in Chrome at 1440 and 1920 px; scan reveal, loupe, row profile, chart click-through and verification polling exercised; layout defects found in review were fixed (viewer overflow, scaled SVG text, label collisions, table overflow) |
| Frontend checks | ESLint and `tsc` clean; 12 Vitest tests; 2 Playwright e2e tests pass against both the dev server and the production build served by the API |
| Lint | `ruff check .` clean |

## Not done or not verified

| Item | Status |
|---|---|
| Docker image and `docker compose` | Written, **not built**: no Docker daemon in the environment |
| GitHub Actions | Workflow written; its result on GitHub is reported in the pull request (not run locally) |
| Public deployment | **Not deployed**: no hosting credentials. Exact steps are in `docs/deployment.md` |
| NIST box-assembly ingestion | Blocked: download refused by the environment's network policy; contents not inspected, nothing assumed |
| Carparts-Seg | Not integrated: licence ambiguous (AGPL-3.0 vs CC BY 4.0) |
| Bosch benchmark | Not attempted: needs a Kaggle sign-in |
| Flush measurement | Out of scope without calibrated depth data |
| Hem-shading bias correction | Not implemented; documented |

## Open defects and next steps

1. Run the Docker build and compose stack on a machine with Docker; fix anything it surfaces.
2. Deploy (managed Postgres + one Docker web service, `FITTRACE_DEMO_READONLY=true`) and run the e2e suite against the public URL.
3. Download the NIST `mtc.zip` locally, inspect it, and add a separate `real` dataset track.
4. Add a reference-artefact bias correction and a GUM-style uncertainty budget.
5. Add multiple change points or a self-starting CUSUM to reduce the 55% short-baseline false-alarm rate.
6. Bundle size: Plotly is lazy-loaded (451 kB gzip); a custom-trace build could shrink it further.
