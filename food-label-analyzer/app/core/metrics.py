from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import math
import os
import threading
from typing import Any

_MAX_SAMPLES = 2048
_HISTOGRAM_BUCKETS_MS = (100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 300000)
_histograms: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
_metrics_lock = threading.RLock()


def _counter_key(
    name: str,
    labels: dict[str, str] | None = None,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized_labels = tuple(sorted((labels or {}).items()))
    return name, normalized_labels


def observe_histogram(name: str, value_ms: int | float) -> None:
    normalized_value = max(0, int(value_ms))
    with _metrics_lock:
        _histograms[name].append(normalized_value)


def increment_counter(
    name: str,
    labels: dict[str, str] | None = None,
    amount: int = 1,
) -> None:
    if amount <= 0:
        return
    with _metrics_lock:
        _counters[_counter_key(name, labels)] += amount


def _percentile(sorted_values: list[int], percentile: float) -> int | None:
    if not sorted_values:
        return None
    index = max(0, math.ceil((percentile / 100) * len(sorted_values)) - 1)
    return sorted_values[min(index, len(sorted_values) - 1)]


def _build_buckets(values: list[int]) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for bucket in _HISTOGRAM_BUCKETS_MS:
        buckets[f"le_{bucket}"] = sum(1 for value in values if value <= bucket)
    buckets[f"gt_{_HISTOGRAM_BUCKETS_MS[-1]}"] = sum(
        1 for value in values if value > _HISTOGRAM_BUCKETS_MS[-1]
    )
    return buckets


def _snapshot_histogram(values: deque[int]) -> dict[str, Any]:
    current_values = list(values)
    sorted_values = sorted(current_values)
    count = len(current_values)
    total = sum(current_values)
    return {
        "count": count,
        "sum_ms": total,
        "min_ms": sorted_values[0] if sorted_values else None,
        "max_ms": sorted_values[-1] if sorted_values else None,
        "avg_ms": round(total / count, 2) if count else None,
        "p50_ms": _percentile(sorted_values, 50),
        "p95_ms": _percentile(sorted_values, 95),
        "p99_ms": _percentile(sorted_values, 99),
        "buckets": _build_buckets(current_values),
    }


def record_analysis_task_metrics(
    *,
    status: str,
    total_elapsed_ms: int,
    timings: dict[str, int],
) -> None:
    increment_counter("analysis_task.status", {"status": status})
    observe_histogram("analysis_task.total_ms", total_elapsed_ms)
    for timing_name, duration_ms in timings.items():
        stage = timing_name.removesuffix("_ms")
        observe_histogram(f"analysis_task.stage.{stage}_ms", duration_ms)


def record_external_dependency_error(
    *,
    service: str,
    operation: str,
    error_type: str,
) -> None:
    increment_counter(
        "external_dependency_errors",
        {
            "service": service,
            "operation": operation,
            "error_type": error_type,
        },
    )


def get_metrics_snapshot() -> dict[str, Any]:
    with _metrics_lock:
        histograms = {
            name: _snapshot_histogram(values)
            for name, values in sorted(_histograms.items())
        }
        counters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (name, labels), value in sorted(_counters.items()):
            counters[name].append(
                {
                    "labels": dict(labels),
                    "value": value,
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc),
        "process": {"pid": os.getpid()},
        "histograms": histograms,
        "counters": dict(counters),
    }


def reset_metrics_for_tests() -> None:
    with _metrics_lock:
        _histograms.clear()
        _counters.clear()


__all__ = [
    "get_metrics_snapshot",
    "increment_counter",
    "observe_histogram",
    "record_analysis_task_metrics",
    "record_external_dependency_error",
    "reset_metrics_for_tests",
]
