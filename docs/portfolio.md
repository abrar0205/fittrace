# FitTrace: portfolio summary

**FitTrace** is a dimensional quality engineering platform I designed and built end to end. It measures automotive panel gaps in calibrated inspection images, traces each result to the unit's manufacturing history, and investigates out-of-tolerance deviations down to statistically supported process contributors. All data comes from documented simulations with known ground truth, so every claim can be checked.

- **Python software engineering:** a modular FastAPI monolith with typed contracts, a scientific core without framework dependencies, structured logging with request IDs, and a PostgreSQL-backed job queue with retries and crash recovery.
- **Industrial ETL:** MES-style exports loaded atomically, idempotently (by file checksum and natural keys) and incrementally. A reject-rate quality gate, auditable rejected rows and data-quality checks are included, and failed runs can be retried from the UI.
- **PostgreSQL and SQL analytics:** a 28-table schema with constraints and query-driven indexes, reversible Alembic migrations, and reviewed analytical SQL for deviation trends, station distributions, unit routes and pipeline health.
- **Computer vision:** an OpenCV sub-pixel gap algorithm, benchmarked against generated ground truth across nine conditions. Bias is +23.5 µm (from modelled hem shading), RMSE 23.7 µm, with explicit failure modes instead of fabricated values.
- **Manufacturing traceability:** each unit has a station, equipment and parameter route linked to its inspections and to the equipment events before it was built.
- **Statistical investigation:** I-MR charts with applicability checks, permutation-tested change points, and difference-in-differences attribution with HC3 errors and Benjamini-Hochberg control. Evaluated on 80 simulated histories: 100% top-1 recovery on full history, 65% sixty units after the alarm, and 5% false attribution, with CUSUM false alarms reported honestly at 55%.
- **Testing and delivery:** 62 Python tests, including integration tests on real PostgreSQL; 12 Vitest and 2 Playwright end-to-end tests; GitHub Actions; and a single-image Docker deployment design.
- **Engineering UI:** a React and TypeScript workbench in the visual language of engineering drawings. It has dimension-line overlays, a pixel loupe, a scan-line replay of the algorithm and a caliper-style tolerance gauge, all driven by stored algorithm output.

Independent project; not affiliated with any manufacturer, and no real factory data is used.
