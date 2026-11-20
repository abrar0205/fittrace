# Deployment

**Status: not deployed.** No hosting credentials were available, so no public URL exists yet. These are the exact steps.

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
