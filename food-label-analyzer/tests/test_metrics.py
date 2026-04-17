from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.error_handlers import register_exception_handlers
from app.core.errors import EmbeddingServiceError, OCRServiceError
from app.workers.ocr_worker import OCRTextResult, TableRecognitionResult
from tests.conftest import load_required_env


@pytest.fixture(autouse=True)
def reset_metrics_state() -> None:
    metrics_module = importlib.import_module("app.core.metrics")
    metrics_module.reset_metrics_for_tests()
    yield
    metrics_module.reset_metrics_for_tests()


def test_metrics_snapshot_records_histograms_percentiles_and_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    metrics_module = importlib.reload(importlib.import_module("app.core.metrics"))
    metrics_module.reset_metrics_for_tests()

    metrics_module.record_analysis_task_metrics(
        status="completed",
        total_elapsed_ms=1234,
        timings={"download_ms": 100, "ocr_ms": 340},
    )
    metrics_module.record_analysis_task_metrics(
        status="failed",
        total_elapsed_ms=2200,
        timings={"download_ms": 120, "ocr_ms": 880},
    )
    metrics_module.record_external_dependency_error(
        service="ocr",
        operation="parallel_fallback",
        error_type="OCRServiceError",
    )

    snapshot = metrics_module.get_metrics_snapshot()

    assert snapshot["histograms"]["analysis_task.total_ms"]["count"] == 2
    assert snapshot["histograms"]["analysis_task.total_ms"]["p95_ms"] == 2200
    assert snapshot["histograms"]["analysis_task.total_ms"]["p99_ms"] == 2200
    assert snapshot["histograms"]["analysis_task.stage.download_ms"]["count"] == 2
    assert snapshot["histograms"]["analysis_task.stage.ocr_ms"]["max_ms"] == 880
    assert snapshot["process"]["pid"] > 0
    assert snapshot["counters"]["analysis_task.status"] == [
        {"labels": {"status": "completed"}, "value": 1},
        {"labels": {"status": "failed"}, "value": 1},
    ]
    assert snapshot["counters"]["external_dependency_errors"] == [
        {
            "labels": {
                "service": "ocr",
                "operation": "parallel_fallback",
                "error_type": "OCRServiceError",
            },
            "value": 1,
        }
    ]


def test_metrics_endpoint_returns_current_process_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    metrics_module = importlib.reload(importlib.import_module("app.core.metrics"))
    metrics_api = importlib.reload(importlib.import_module("app.api.v1.metrics"))
    metrics_module.reset_metrics_for_tests()
    metrics_module.record_analysis_task_metrics(
        status="completed",
        total_elapsed_ms=512,
        timings={"ocr_ms": 200},
    )

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(metrics_api.router, prefix="/metrics")
    app.dependency_overrides[metrics_api.get_current_user] = (
        lambda: SimpleNamespace(id="user-1")
    )

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 0
    assert payload["data"]["process"]["pid"] > 0
    assert payload["data"]["histograms"]["analysis_task.total_ms"]["count"] == 1
    assert payload["data"]["counters"]["analysis_task.status"] == [
        {"labels": {"status": "completed"}, "value": 1}
    ]


def test_ocr_strategy_records_nonfatal_fallback_dependency_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    ocr_strategy_module = importlib.reload(
        importlib.import_module("app.tasks.analysis.ocr_strategy")
    )
    dependency_errors: list[dict[str, str]] = []

    monkeypatch.setattr(
        ocr_strategy_module,
        "record_external_dependency_error",
        lambda **kwargs: dependency_errors.append(kwargs),
    )
    monkeypatch.setattr(
        ocr_strategy_module,
        "_run_ocr_parallel",
        lambda *args, **kwargs: (_ for _ in ()).throw(OCRServiceError("parallel down")),
    )
    monkeypatch.setattr(
        ocr_strategy_module,
        "_run_ocr_full_text",
        lambda image_bytes: OCRTextResult(
            raw_text="salt",
            lines=[],
            blocks=[],
            artifact_json_url=None,
        ),
    )
    monkeypatch.setattr(
        ocr_strategy_module,
        "_run_ocr_table",
        lambda image_bytes: TableRecognitionResult(
            table_json={"rows": [["item", "per100g"], ["energy", "120kJ"]]},
            ocr_fallback_text="energy 120kJ",
        ),
    )

    full_text_result, table_result = ocr_strategy_module._run_ocr_with_bbox_fallback(
        task_id="task-1",
        image_bytes=b"img",
        masked_full_image=b"masked",
        cropped_image=b"cropped",
    )

    assert full_text_result.raw_text == "salt"
    assert table_result is not None
    assert dependency_errors == [
        {
            "service": "ocr",
            "operation": "parallel_fallback",
            "error_type": "OCRServiceError",
        }
    ]


def test_rag_worker_records_embedding_errors_for_batch_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch)
    rag_worker_module = importlib.reload(importlib.import_module("app.workers.rag_worker"))
    dependency_errors: list[dict[str, str]] = []

    monkeypatch.setattr(
        rag_worker_module,
        "record_external_dependency_error",
        lambda **kwargs: dependency_errors.append(kwargs),
    )
    monkeypatch.setattr(
        rag_worker_module,
        "_embed_batch",
        lambda texts: (_ for _ in ()).throw(EmbeddingServiceError("embedding down")),
    )

    payload = rag_worker_module.retrieve_all(["salt", "sugar"], "salt, sugar")

    assert payload["items_total"] == 2
    assert dependency_errors == [
        {
            "service": "embedding",
            "operation": "retrieve_all.embed_batch",
            "error_type": "EmbeddingServiceError",
        }
    ]
