# Deployment

## Public demo: GitHub Pages (live)

**URL:** https://abrar0205.github.io/fittrace/

GitHub Pages serves static files only, so the public demo is a snapshot built by `.github/workflows/pages.yml` on every push to `main` (or by hand from the Actions tab):

1. Start a PostgreSQL 16 service container and run `alembic upgrade head`.
2. Run `python -m app.cli seed-demo`: generate the line, run the 4 import executions (including the corrupt delivery), measure all 1,120 images, and run both benchmarks.
3. Run `python -m app.cli prepare-snapshot`: an investigation for every out-of-tolerance inspection, plus paired verification jobs (the top-ranked target, and one deliberately wrong target).
4. Run `python -m app.cli export-snapshot`: every view the UI needs, requested through the real API via the FastAPI TestClient and written as JSON. Inspection images and benchmark cases are written as PNG. An integration test checks that the exported files equal the API responses.
5. Build the UI with `VITE_SNAPSHOT=1 VITE_BASE=/fittrace/`. `404.html` provides deep-link routing.
6. Serve the result the way Pages does (`scripts/pages_server.py`) and run the Playwright suite against it.
7. Publish to the `gh-pages` branch (single orphan commit, so the branch does not accumulate history).

The snapshot is about 103 MB (mostly the 1,120 lossless PNG images, which the loupe and profile read pixel by pixel). That is well inside the 1 GB Pages limit. The workflow takes about 10–15 minutes.

In snapshot mode, the client (`apps/web/src/api/snapshot.ts`) routes each typed API call to its exported file and applies the same filtering and pagination as the API for the two long lists. Write actions return a read-only error and are disabled in the UI with an explanation.

## Full interactive deployment (optional)

To run everything live (re-runs, new investigations and verifications, retries), host the API as well. No hosting credentials were available, so this is not deployed; these are the exact steps.

## Recommended low-cost setup

- **Database:** a managed PostgreSQL 16 free tier (for example Neon or Supabase). Create a role with only the privileges needed on its own database.
- **App:** one Docker web service (for example Render, Koyeb or Fly.io) built from the root `Dockerfile`. It runs migrations, serves the API and the built UI from the same origin (so no CORS is needed), and runs the job worker in-process.

| Variable | Value |
|---|---|
| `FITTRACE_DATABASE_URL` | `postgresql+psycopg://USER:PASSWORD@HOST/DB?sslmode=require` (set as a secret, never committed) |
| `FITTRACE_RUN_WORKER_IN_PROCESS` | `true` |
| `FITTRACE_SEED_ON_START` | `true` (idempotent; regenerates identical images on ephemeral disks) |
| `FITTRACE_DEMO_READONLY` | `true` (caps interactive re-runs, disables pipeline retry) |
| `FITTRACE_MAX_VERIFICATION_UNITS` | `120` |
| `FITTRACE_CORS_ORIGINS` | `[]` for same-origin, or the UI origin if it is hosted separately |
| `PORT` | provided by the host |

Health check path: `/healthz`. The first start seeds in the background (about 1 min of data plus about 2 min of benchmarks). Until then, the sheets show their "no data" states with instructions.

Free tiers usually suspend idle services, so the first request after a pause can take 30–60 s. Images are regenerated on cold start if the disk was wiped.

## Steps

1. `docker build -t fittrace .` and `docker run -p 8000:8000 -e FITTRACE_DATABASE_URL=... -e FITTRACE_SEED_ON_START=true -e FITTRACE_RUN_WORKER_IN_PROCESS=true fittrace` to test locally.
2. Create the managed database and copy its connection string into the host's secret settings.
3. Create the web service from the GitHub repository (Dockerfile build) and set the variables above.
4. After the deploy, verify: `/api/v1/health` returns `database: ok`; the Overview shows 560 units; an out-of-tolerance inspection opens its investigation; a verification job completes; the Pipelines sheet shows the four seeded import runs.
5. Point the e2e suite at it: `E2E_BASE_URL=https://<host> npx playwright test`.

## Separate frontend hosting (optional)

Build with `VITE_API_BASE=https://<api-host> npm run build`, host `apps/web/dist` on any static host with an SPA fallback to `index.html`, and set `FITTRACE_CORS_ORIGINS='["https://<ui-host>"]'` on the API.
