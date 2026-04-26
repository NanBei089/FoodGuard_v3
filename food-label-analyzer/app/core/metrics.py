"""项目通用能力，比如配置、日志、安全、异常和监控。"""


from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
import importlib
import math
import os
from pathlib import Path
import threading
from typing import Any

from app.core.config import get_settings

_settings = get_settings()
if _settings.prometheus_multiproc_enabled:
    os.environ.setdefault(
        "PROMETHEUS_MULTIPROC_DIR",
        _settings.PROMETHEUS_MULTIPROC_DIR.strip(),
    )

from prometheus_client import values as prometheus_values

importlib.reload(prometheus_values)

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram
from prometheus_client import generate_latest, multiprocess

_MAX_SAMPLES = 2048
_HISTOGRAM_BUCKETS_MS = (100, 250, 500, 1000, 2500, 5000, 10000, 30000, 60000, 300000)
_PROMETHEUS_HISTOGRAM_BUCKETS_S = tuple(bucket / 1000 for bucket in _HISTOGRAM_BUCKETS_MS)
_histograms: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))
_counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = defaultdict(int)
_metrics_lock = threading.RLock()
_prometheus_registry = CollectorRegistry(auto_describe=True)

_analysis_task_status_counter = Counter(
    "analysis_task_status",
    "Total number of analysis task attempts by final status.",
    ["status"],
    registry=_prometheus_registry,
)
_analysis_task_duration_histogram = Histogram(
    "analysis_task_duration_seconds",
    "Total analysis task duration in seconds.",
    buckets=_PROMETHEUS_HISTOGRAM_BUCKETS_S,
    registry=_prometheus_registry,
)
_analysis_task_stage_duration_histogram = Histogram(
    "analysis_task_stage_duration_seconds",
    "Analysis task stage duration in seconds.",
    ["stage"],
    buckets=_PROMETHEUS_HISTOGRAM_BUCKETS_S,
    registry=_prometheus_registry,
)
_external_dependency_error_counter = Counter(
    "external_dependency_errors",
    "Total number of external dependency errors observed by service and operation.",
    ["service", "operation", "error_type"],
    registry=_prometheus_registry,
)


def _counter_key(
    name: str,
    labels: dict[str, str] | None = None,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized_labels = tuple(sorted((labels or {}).items()))
    return name, normalized_labels


def _prometheus_multiproc_dir() -> str:
    return _settings.PROMETHEUS_MULTIPROC_DIR.strip()


def prepare_prometheus_storage() -> str | None:
    multiproc_dir = _prometheus_multiproc_dir()
    if not multiproc_dir:
        return None

    storage_path = Path(multiproc_dir)
    storage_path.mkdir(parents=True, exist_ok=True)
    return str(storage_path)


def mark_prometheus_process_dead(pid: int | None = None) -> None:
    multiproc_dir = _prometheus_multiproc_dir()
    if not multiproc_dir:
        return

    process_id = pid if pid is not None else os.getpid()
    multiprocess.mark_process_dead(process_id)


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
    """记录运行状态，方便后续监控或排查。"""
    increment_counter("analysis_task.status", {"status": status})
    observe_histogram("analysis_task.total_ms", total_elapsed_ms)
    _analysis_task_status_counter.labels(status=status).inc()
    _analysis_task_duration_histogram.observe(total_elapsed_ms / 1000)
    for timing_name, duration_ms in timings.items():
        stage = timing_name.removesuffix("_ms")
        observe_histogram(f"analysis_task.stage.{stage}_ms", duration_ms)
        _analysis_task_stage_duration_histogram.labels(stage=stage).observe(
            duration_ms / 1000
        )


def record_external_dependency_error(
    *,
    service: str,
    operation: str,
    error_type: str,
) -> None:
    """记录运行状态，方便后续监控或排查。"""
    increment_counter(
        "external_dependency_errors",
        {
            "service": service,
            "operation": operation,
            "error_type": error_type,
        },
    )
    _external_dependency_error_counter.labels(
        service=service,
        operation=operation,
        error_type=error_type,
    ).inc()


def generate_prometheus_latest() -> bytes:
    if _prometheus_multiproc_dir():
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        return generate_latest(registry)
    return generate_latest(_prometheus_registry)


def prometheus_content_type() -> str:
    return CONTENT_TYPE_LATEST


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
    "generate_prometheus_latest",
    "get_metrics_snapshot",
    "increment_counter",
    "mark_prometheus_process_dead",
    "observe_histogram",
    "prepare_prometheus_storage",
    "prometheus_content_type",
    "record_analysis_task_metrics",
    "record_external_dependency_error",
    "reset_metrics_for_tests",
]
