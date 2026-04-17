from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import BASE_MODEL_CONFIG


class _MetricsSchema(BaseModel):
    model_config = BASE_MODEL_CONFIG


class ProcessMetricsSchema(_MetricsSchema):
    pid: int = Field(description="Current process ID", examples=[12345])


class HistogramMetricsSchema(_MetricsSchema):
    count: int = Field(description="Observed sample count", examples=[12])
    sum_ms: int = Field(description="Observed total in milliseconds", examples=[3400])
    min_ms: int | None = Field(description="Minimum observed duration", examples=[12])
    max_ms: int | None = Field(description="Maximum observed duration", examples=[880])
    avg_ms: float | None = Field(description="Average observed duration", examples=[283.3])
    p50_ms: int | None = Field(description="P50 duration", examples=[120])
    p95_ms: int | None = Field(description="P95 duration", examples=[740])
    p99_ms: int | None = Field(description="P99 duration", examples=[860])
    buckets: dict[str, int] = Field(description="Cumulative histogram buckets")


class CounterMetricsItemSchema(_MetricsSchema):
    labels: dict[str, str] = Field(description="Metric label set")
    value: int = Field(description="Counter value", examples=[3])


class MetricsSnapshotResponse(_MetricsSchema):
    generated_at: datetime = Field(
        description="Snapshot generation time",
        examples=["2026-04-17T12:30:00Z"],
    )
    process: ProcessMetricsSchema = Field(description="Current process metadata")
    histograms: dict[str, HistogramMetricsSchema] = Field(
        description="Recorded histogram metrics by name"
    )
    counters: dict[str, list[CounterMetricsItemSchema]] = Field(
        description="Recorded counters by name"
    )


__all__ = [
    "CounterMetricsItemSchema",
    "HistogramMetricsSchema",
    "MetricsSnapshotResponse",
    "ProcessMetricsSchema",
]
