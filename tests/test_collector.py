"""Check the collection loop without network or database access."""

import threading
import time

import psycopg
import pytest

from mobility.cli import main
from mobility.ingestion.collector import collect


def stop_after(calls: int, stop: threading.Event, error: Exception | None = None):
    count = 0

    def run_once() -> None:
        nonlocal count
        count += 1
        if count == calls:
            stop.set()
        elif error is not None:
            raise error

    return run_once, lambda: count


def test_collect_runs_until_stopped() -> None:
    stop = threading.Event()
    run_once, calls = stop_after(3, stop)

    collect(run_once, interval=0.001, stop=stop)

    assert calls() == 3


def test_collect_survives_unavailable_database() -> None:
    stop = threading.Event()
    run_once, calls = stop_after(2, stop, psycopg.OperationalError("refused"))

    collect(run_once, interval=0.001, stop=stop)

    assert calls() == 2


def test_collect_propagates_other_errors() -> None:
    stop = threading.Event()
    run_once, _ = stop_after(2, stop, ValueError("bug"))

    with pytest.raises(ValueError):
        collect(run_once, interval=0.001, stop=stop)


def test_collect_does_not_wait_for_next_cycle_after_stop() -> None:
    stop = threading.Event()
    run_once, _ = stop_after(1, stop)
    started = time.monotonic()

    collect(run_once, interval=10, stop=stop)

    assert time.monotonic() - started < 1


@pytest.mark.parametrize("interval", ["0", "-5", "soon"])
def test_collect_realtime_rejects_invalid_interval(interval: str) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["collect-realtime", "--interval", interval])

    assert exit_info.value.code == 2
