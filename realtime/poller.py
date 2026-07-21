import time
from typing import Iterable
from realtime.siri_client import get_upcoming_vehicles
from realtime.models import StopVisit


def poll_stops(monitoring_refs: Iterable[str], use_test_env: bool = False) -> dict[str, list[StopVisit]]:
    """Fetches current upcoming vehicles for a set of stops. One call per stop."""
    results = {}
    for ref in monitoring_refs:
        try:
            results[ref] = get_upcoming_vehicles(ref, use_test_env=use_test_env)
        except Exception as e:
            print(f"[poller] failed for stop {ref}: {e}")
            results[ref] = []
    return results


def poll_loop(monitoring_refs: Iterable[str], interval_seconds: int = 30, use_test_env: bool = False):
    """Simple blocking poll loop — swap for async/celery/etc. later."""
    while True:
        data = poll_stops(monitoring_refs, use_test_env=use_test_env)
        yield data
        time.sleep(interval_seconds)