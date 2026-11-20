from __future__ import annotations

import logging
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes.v1 import router as v1
from app.core.config import REPO_ROOT, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, log, request_id_var
from fittrace import __version__

logger = logging.getLogger("fittrace.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    stop = threading.Event()
    t = None
    if s.run_worker_in_process:
        from app.services.jobs import worker_loop

        t = threading.Thread(target=worker_loop, args=(stop,), name="fittrace-worker", daemon=True)
        t.start()
        log(logger, logging.INFO, "in-process worker started")
    yield
    stop.set()
    if t:
        t.join(timeout=5)


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    app = FastAPI(
        title="FitTrace API",
        version=__version__,
        description=(
            "Dimensional inspection, manufacturing traceability and quality investigation. "
            "All production data served by the demo is **simulated**; inspection images are procedurally generated "
            "with known calibration."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type", "X-Request-ID"], expose_headers=["X-Request-ID"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        token = request_id_var.set(rid)
        t0 = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        if request.url.path.startswith("/api/"):
            log(logger, logging.INFO, "request", method=request.method, path=request.url.path,
                status=response.status_code, ms=round((time.perf_counter() - t0) * 1000, 1), request_id=rid)
        return response

    install_error_handlers(app)
    app.include_router(v1)

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok"}

    # Optional: serve the built frontend from the same origin (single-service deploys).
    web_dist = Path(REPO_ROOT / "apps" / "web" / "dist")
    if web_dist.is_dir():
        app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            candidate = (web_dist / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(web_dist.resolve()):
                return FileResponse(candidate)
            return FileResponse(web_dist / "index.html")

    return app


app = create_app()
