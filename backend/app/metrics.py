import threading

# Bound on how many raw duration samples are kept per bucket, so a
# long-running process doesn't accumulate an unbounded list in memory.
_MAX_SAMPLES = 500


class Metrics:
    """In-memory counters and duration samples.

    No external dependency (no Prometheus client, no metrics backend) --
    appropriate for a single-instance deployment like this one on Render.
    Resets on process restart. If this project ever runs multiple
    instances behind a load balancer, these counters stop being accurate
    in aggregate and should be replaced with a real metrics backend
    instead of trying to reconcile several processes' in-memory state.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._counters = {
            "ingests_total": 0,
            "ingests_failed_total": 0,
            "queries_total": 0,
            "queries_failed_total": 0,
            "quota_errors_total": 0,
        }
        self._durations_ms: dict[str, list] = {}

    def increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + amount

    def record_duration(self, key: str, duration_ms: float) -> None:
        with self._lock:
            bucket = self._durations_ms.setdefault(key, [])
            bucket.append(duration_ms)
            if len(bucket) > _MAX_SAMPLES:
                del bucket[: len(bucket) - _MAX_SAMPLES]

    def snapshot(self) -> dict:
        with self._lock:
            avg_durations = {
                f"avg_{key}": (round(sum(values) / len(values), 1) if values else None)
                for key, values in self._durations_ms.items()
            }
            return {**self._counters, **avg_durations}


metrics = Metrics()
