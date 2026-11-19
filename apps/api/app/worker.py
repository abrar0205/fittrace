"""Standalone job worker: ``python -m app.worker``."""

from __future__ import annotations

import signal
import threading

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.services.jobs import worker_loop


def main() -> None:
    s = get_settings()
    configure_logging(s.log_level, s.log_json)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    worker_loop(stop)


if __name__ == "__main__":
    main()
