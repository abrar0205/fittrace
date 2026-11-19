#!/bin/sh
# Migrate, optionally (re)seed in the background, then serve.
# Seeding is idempotent and deterministic: on hosts with ephemeral disks it
# regenerates byte-identical images, and the import pipeline skips unchanged files.
set -e
alembic upgrade head
if [ "${FITTRACE_SEED_ON_START:-false}" = "true" ]; then
  ( python -m app.cli seed-demo ${FITTRACE_SEED_ARGS:-} >> /tmp/seed.log 2>&1 || echo "seed failed, see /tmp/seed.log" ) &
fi
if [ "${1:-api}" = "worker" ]; then
  exec python -m app.worker
fi
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers
