from __future__ import annotations

import json
import time
from typing import Any

import requests
import structlog

from app.workers.ocr.types import OCRConfig

logger = structlog.get_logger(__name__)

_RESULT_DOWNLOAD_RETRYABLE_STATUS_CODES = {403, 404, 409, 425, 429, 500, 502, 503, 504}
_RESULT_DOWNLOAD_MAX_ATTEMPTS = 3
_RESULT_DOWNLOAD_RETRY_DELAY_S = 1.0


class PaddleOCRAPIClient:
    def __init__(self, config: OCRConfig) -> None:
        self.config = config
        if not config.job_url.strip():
            raise RuntimeError("PaddleOCR job URL is not configured")
        if not config.token.strip():
            raise RuntimeError("PaddleOCR token is not configured")
        if not config.model.strip():
            raise RuntimeError("PaddleOCR model is not configured")

    def describe(self) -> dict[str, Any]:
        return {
            "lang": self.config.lang,
            "use_angle_cls": self.config.use_angle_cls,
            "model": self.config.model,
            "mode": "online_api",
            "device": self.config.device,
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"bearer {self.config.token}"}

    def _build_optional_payload(self) -> dict[str, Any]:
        return {
            "useDocOrientationClassify": bool(self.config.use_doc_orientation_classify),
            "useDocUnwarping": bool(self.config.use_doc_unwarping),
            "useTextlineOrientation": bool(self.config.use_textline_orientation),
            "useSealRecognition": bool(self.config.use_seal_recognition),
            "useTableRecognition": bool(self.config.use_table_recognition),
            "useE2eWiredTableRecModel": bool(self.config.use_e2e_wired_table_rec_model),
            "useE2eWirelessTableRecModel": bool(
                self.config.use_e2e_wireless_table_rec_model
            ),
            "useFormulaRecognition": bool(self.config.use_formula_recognition),
            "useChartRecognition": bool(self.config.use_chart_recognition),
            "textDetBoxThresh": float(self.config.det_db_box_thresh),
            "textDetUnclipRatio": float(self.config.det_db_unclip_ratio),
            "textDetLimitSideLen": int(self.config.text_det_limit_side_len),
            "textDetLimitType": str(self.config.text_det_limit_type),
            "textDetThresh": float(self.config.text_det_thresh),
        }

    def _submit_job(self, image_bytes: bytes, filename: str = "image.jpg") -> str:
        data = {
            "model": self.config.model,
            "optionalPayload": json.dumps(
                self._build_optional_payload(), ensure_ascii=False
            ),
        }
        files = {"file": (filename, image_bytes, "application/octet-stream")}
        response = requests.post(
            self.config.job_url,
            headers=self._headers(),
            data=data,
            files=files,
            timeout=self.config.request_timeout_s,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"OCR job submission failed: HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError("OCR job submission returned invalid JSON") from exc

        try:
            return str(payload["data"]["jobId"])
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                f"OCR job response did not include jobId: {payload}"
            ) from exc

    def _poll_job(self, job_id: str) -> dict[str, Any]:
        job_status_url = f"{self.config.job_url}/{job_id}"
        deadline = time.monotonic() + self.config.poll_timeout_s

        while time.monotonic() < deadline:
            response = requests.get(
                job_status_url,
                headers=self._headers(),
                timeout=self.config.request_timeout_s,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"OCR job polling failed: HTTP {response.status_code}: {response.text}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise RuntimeError("OCR job polling returned invalid JSON") from exc

            data = payload.get("data") or {}
            state = data.get("state")
            if state == "done":
                return data
            if state == "failed":
                raise RuntimeError(
                    f"OCR job failed: {data.get('errorMsg', 'unknown error')}"
                )
            if state not in {"pending", "running"}:
                raise RuntimeError(f"Unexpected OCR job state: {payload}")

            time.sleep(self.config.poll_interval_s)

        raise TimeoutError(
            f"OCR job timed out after {self.config.poll_timeout_s} seconds. job_id={job_id}"
        )

    def _download_jsonl_results(self, json_url: str) -> list[Any]:
        last_error: Exception | None = None
        for attempt in range(1, _RESULT_DOWNLOAD_MAX_ATTEMPTS + 1):
            try:
                response = requests.get(json_url, timeout=self.config.request_timeout_s)
                response.raise_for_status()

                response_text = response.content.decode("utf-8", errors="replace")
                results: list[Any] = []
                for raw_line in response_text.splitlines():
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(item, dict) and "result" in item:
                        results.append(item["result"])
                    else:
                        results.append(item)
                return results
            except requests.HTTPError as exc:
                last_error = exc
                status_code = exc.response.status_code if exc.response is not None else None
                should_retry = (
                    attempt < _RESULT_DOWNLOAD_MAX_ATTEMPTS
                    and status_code in _RESULT_DOWNLOAD_RETRYABLE_STATUS_CODES
                )
                if not should_retry:
                    raise
                logger.warning(
                    "ocr_result_download_retrying",
                    attempt=attempt,
                    max_attempts=_RESULT_DOWNLOAD_MAX_ATTEMPTS,
                    status_code=status_code,
                )
                time.sleep(_RESULT_DOWNLOAD_RETRY_DELAY_S)
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= _RESULT_DOWNLOAD_MAX_ATTEMPTS:
                    raise
                logger.warning(
                    "ocr_result_download_retrying",
                    attempt=attempt,
                    max_attempts=_RESULT_DOWNLOAD_MAX_ATTEMPTS,
                    status_code=None,
                )
                time.sleep(_RESULT_DOWNLOAD_RETRY_DELAY_S)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OCR result download failed without explicit exception")

    def ocr(self, image_bytes: bytes, filename: str = "image.jpg") -> dict[str, Any]:
        job_id = self._submit_job(image_bytes, filename)
        job_data = self._poll_job(job_id)
        result_url = job_data.get("resultUrl") or {}
        json_url = result_url.get("jsonUrl") or result_url.get("jsonlUrl")
        if not json_url:
            raise RuntimeError(
                f"OCR job completed but result URL is missing: {job_data}"
            )

        results = self._download_jsonl_results(str(json_url))
        return {
            "job_id": job_id,
            "json_url": str(json_url),
            "results": results,
        }


PaddleOCR = PaddleOCRAPIClient
