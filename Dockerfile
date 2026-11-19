# Single image: FastAPI API + job worker + built React app (served from the same origin).
FROM node:22-alpine AS web
WORKDIR /src/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 FITTRACE_DATA_DIR=/data PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY packages/fittrace packages/fittrace
COPY apps/api apps/api
RUN pip install -e packages/fittrace -e apps/api
COPY database database
COPY scripts/docker-entrypoint.sh scripts/docker-entrypoint.sh
COPY --from=web /src/apps/web/dist apps/web/dist
RUN useradd --create-home --uid 10001 fittrace && mkdir -p /data && chown fittrace /data
USER fittrace
WORKDIR /app/apps/api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fs http://localhost:${PORT:-8000}/healthz || exit 1
ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
