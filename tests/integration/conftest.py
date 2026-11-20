"""Integration fixtures: a real PostgreSQL database, migrated with Alembic.

Set FITTRACE_TEST_DATABASE_URL (default: local fittrace_test database). The
schema is dropped and rebuilt for each test session.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TEST_DB = os.environ.get("FITTRACE_TEST_DATABASE_URL",
                         "postgresql+psycopg://fittrace:fittrace@localhost:5432/fittrace_test")
DATA_DIR = Path(tempfile.mkdtemp(prefix="fittrace-test-"))
os.environ["FITTRACE_DATABASE_URL"] = TEST_DB
os.environ["FITTRACE_DATA_DIR"] = str(DATA_DIR)
os.environ["FITTRACE_LOG_JSON"] = "false"
os.environ["FITTRACE_LOG_LEVEL"] = "WARNING"

KEY = "test-ds"
N_UNITS = 160
FAULT_AT = 90


def _alembic(cmd: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO / "apps" / "api" / "alembic.ini"))
    getattr(command, cmd)(cfg, rev)


@pytest.fixture(scope="session")
def engine():
    from sqlalchemy import create_engine, text

    eng = create_engine(TEST_DB)
    try:
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available for integration tests: {e}")
    _alembic("upgrade", "head")
    _alembic("downgrade", "base")  # migrations must be reversible
    _alembic("upgrade", "head")
    yield eng
    eng.dispose()
    shutil.rmtree(DATA_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def export_dir():
    from fittrace.simulation.export import write_export
    from fittrace.simulation.factory import Fault, SimConfig, simulate

    res = simulate(SimConfig(seed=77, n_units=N_UNITS, faults=[Fault("fixture_shift", "FX-202", FAULT_AT, 0.5)]))
    out = DATA_DIR / "raw" / KEY
    manifest = write_export(res, out, KEY, dq_defect_rate=0.02, dq_seed=3, workers=2)
    return out, manifest, res


@pytest.fixture(scope="session")
def seeded(engine, export_dir):
    from app.pipelines.measure import run_measurement_pipeline
    from app.pipelines.mes_import import run_mes_import

    out, manifest, res = export_dir
    first = run_mes_import(out, KEY, "integration test dataset")
    measure = run_measurement_pipeline(KEY)
    return {"import_run": first, "measure_run": measure, "manifest": manifest, "sim": res, "dir": out}


@pytest.fixture()
def db(engine):
    from app.core.db import get_sessionmaker

    s = get_sessionmaker()()
    yield s
    s.close()


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c
