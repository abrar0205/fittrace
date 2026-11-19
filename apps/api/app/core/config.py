from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Environment-based configuration. See .env.example for every variable."""

    model_config = SettingsConfigDict(env_prefix="FITTRACE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fittrace:fittrace@localhost:5432/fittrace"
    data_dir: Path = REPO_ROOT / "data"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"])
    log_level: str = "INFO"
    log_json: bool = True
    # Public-demo safeguards
    demo_readonly: bool = False
    max_verification_units: int = 200
    max_queued_jobs: int = 4
    # Run the job worker as a thread inside the API process (single-service deploys)
    run_worker_in_process: bool = False
    worker_poll_seconds: float = 1.0
    reject_rate_gate: float = 0.05
    page_size_max: int = 500


@lru_cache
def get_settings() -> Settings:
    return Settings()
