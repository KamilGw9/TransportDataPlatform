import logging
import threading
import time
from collections.abc import Callable

import psycopg

logger = logging.getLogger(__name__)


def collect(
    run_once: Callable[[], object], interval: float, stop: threading.Event
) -> None:
    """Call run_once every interval seconds until stop is set.

    A cycle that is running when stop is set finishes first, so every download
    that started is also recorded.
    """
    next_run = time.monotonic()
    while not stop.is_set():
        try:
            run_once()
        except psycopg.OperationalError as e:
            # PostgreSQL may restart while the collector runs. Skip this cycle;
            # the next one opens a new connection.
            logger.error("Database unavailable, skipping cycle: %s", e)
        next_run = max(next_run + interval, time.monotonic())
        stop.wait(next_run - time.monotonic())
