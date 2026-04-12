from __future__ import annotations

from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np
import structlog
from PIL import Image

logger = structlog.get_logger(__name__)

ResolvedOCRDevice = Literal["gpu", "cpu"]


def _to_plain_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain_value(item) for item in value]
    if hasattr(value, "tolist") and callable(value.tolist):
        try:
            return value.tolist()
        except (AttributeError, TypeError, ValueError):
            return value
    if isinstance(value, Path):
        return str(value)
    return value


def _import_paddle_module() -> Any:
    try:
        return import_module("paddle")
    except ImportError as exc:
        raise RuntimeError(
            "Local PaddleOCR mode requires paddlepaddle or paddlepaddle-gpu"
        ) from exc


def _import_paddleocr_module() -> Any:
    try:
        return import_module("paddleocr")
    except ImportError as exc:
        raise RuntimeError("Local PaddleOCR mode requires the paddleocr package") from exc


def resolve_device(preference: str) -> ResolvedOCRDevice:
    normalized = (preference or "auto").strip().lower()
    if normalized not in {"auto", "gpu", "cpu"}:
        raise ValueError("PADDLEOCR_DEVICE must be one of auto, gpu, cpu")
    if normalized == "cpu":
        return "cpu"

    try:
        paddle = _import_paddle_module()
        has_cuda = bool(paddle.device.is_compiled_with_cuda())
        device_count = int(paddle.device.cuda.device_count())
    except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as exc:
        logger.warning(
            "paddleocr_gpu_unavailable_fallback_cpu",
            reason="cuda_detection_failed",
            error=str(exc),
        )
        return "cpu"

    if has_cuda and device_count > 0:
        return "gpu"

    logger.warning(
        "paddleocr_gpu_unavailable_fallback_cpu",
        reason="cuda_not_available",
        requested_device=normalized,
    )
    return "cpu"


def ensure_local_runtime_available(preference: str) -> ResolvedOCRDevice:
    device = resolve_device(preference)
    _import_paddleocr_module()
    return device


def _effective_precision(device: ResolvedOCRDevice, precision: str) -> str:
    if device == "gpu":
        return precision
    return "fp32"


def _resolve_paddlex_config(
    model_dir: str | None,
    config_name: str,
) -> str | None:
    if not model_dir:
        return None

    base_path = Path(model_dir)
    candidates = (
        base_path / config_name,
        base_path / "configs" / config_name,
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _image_bytes_to_array(image_bytes: bytes) -> np.ndarray:
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    return np.asarray(image)


def _first_prediction(predictions: Iterable[Any] | Any) -> Any:
    if isinstance(predictions, Iterable) and not isinstance(
        predictions, (bytes, bytearray, dict, str)
    ):
        iterator = iter(predictions)
        try:
            return next(iterator)
        except StopIteration as exc:
            raise RuntimeError("PaddleOCR local prediction returned no results") from exc
    return predictions


def _extract_text_payload(prediction: Any) -> dict[str, Any]:
    candidates = [
        getattr(prediction, "res", None),
        getattr(prediction, "json", None),
        prediction,
    ]
    for candidate in candidates:
        plain = _to_plain_value(candidate)
        if not isinstance(plain, dict):
            continue
        if isinstance(plain.get("res"), dict):
            plain = _to_plain_value(plain["res"])
        if any(
            key in plain
            for key in ("rec_texts", "rec_scores", "dt_polys", "rec_polys", "lines")
        ):
            return plain
    raise RuntimeError("Unexpected PaddleOCR local text prediction format")


def _extract_structure_payload(prediction: Any) -> dict[str, Any]:
    candidates = [
        getattr(prediction, "json", None),
        prediction,
    ]
    for candidate in candidates:
        plain = _to_plain_value(candidate)
        if not isinstance(plain, dict):
            continue
        if isinstance(plain.get("prunedResult"), dict):
            return plain
        if isinstance(plain.get("res"), dict):
            pruned_result = _to_plain_value(plain["res"])
            if isinstance(pruned_result, dict):
                output = {"prunedResult": pruned_result}
                markdown = plain.get("markdown")
                if markdown is not None:
                    output["markdown"] = _to_plain_value(markdown)
                return output

    pruned_result = _to_plain_value(getattr(prediction, "prunedResult", None))
    if isinstance(pruned_result, dict):
        output = {"prunedResult": pruned_result}
        markdown = _to_plain_value(getattr(prediction, "markdown", None))
        if markdown is not None:
            output["markdown"] = markdown
        return output

    raise RuntimeError("Unexpected PPStructureV3 local prediction format")


def _build_local_ocr_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "rec_texts": list(payload.get("rec_texts") or []),
        "rec_scores": list(payload.get("rec_scores") or []),
        "dt_polys": _to_plain_value(
            payload.get("dt_polys")
            or payload.get("rec_polys")
            or payload.get("textline_polys")
            or []
        ),
    }


def _normalize_markdown(markdown: Any) -> dict[str, Any] | None:
    plain = _to_plain_value(markdown)
    if isinstance(plain, dict):
        return plain
    if isinstance(plain, str) and plain.strip():
        return {"text": plain}
    return None


class LocalPaddleOCRClient:
    def __init__(
        self,
        *,
        device: ResolvedOCRDevice,
        precision: str,
        cpu_threads: int,
        enable_mkldnn: bool,
        use_doc_orientation_classify: bool,
        use_doc_unwarping: bool,
        use_textline_orientation: bool,
        text_det_limit_side_len: int,
        text_det_limit_type: str,
        text_det_thresh: float,
        text_det_box_thresh: float,
        text_det_unclip_ratio: float,
        local_model_dir: str | None,
    ) -> None:
        self.device = device
        self.precision = _effective_precision(device, precision)
        self.cpu_threads = cpu_threads
        self.enable_mkldnn = enable_mkldnn
        self.use_doc_orientation_classify = use_doc_orientation_classify
        self.use_doc_unwarping = use_doc_unwarping
        self.use_textline_orientation = use_textline_orientation
        self.text_det_limit_side_len = text_det_limit_side_len
        self.text_det_limit_type = text_det_limit_type
        self.text_det_thresh = text_det_thresh
        self.text_det_box_thresh = text_det_box_thresh
        self.text_det_unclip_ratio = text_det_unclip_ratio
        self.local_model_dir = local_model_dir
        self._engine: Any | None = None

    def _build_engine(self) -> Any:
        paddleocr_module = _import_paddleocr_module()
        engine_class = getattr(paddleocr_module, "PaddleOCR", None)
        if engine_class is None:
            raise RuntimeError("paddleocr.PaddleOCR is not available")

        paddlex_config = _resolve_paddlex_config(self.local_model_dir, "PaddleOCR.yaml")
        kwargs: dict[str, Any] = {
            "lang": "ch",
            "device": self.device,
            "precision": self.precision,
            "use_doc_orientation_classify": self.use_doc_orientation_classify,
            "use_doc_unwarping": self.use_doc_unwarping,
            "use_textline_orientation": self.use_textline_orientation,
            "text_det_limit_side_len": self.text_det_limit_side_len,
            "text_det_limit_type": self.text_det_limit_type,
            "text_det_thresh": self.text_det_thresh,
            "text_det_box_thresh": self.text_det_box_thresh,
            "text_det_unclip_ratio": self.text_det_unclip_ratio,
        }
        if paddlex_config:
            kwargs["paddlex_config"] = paddlex_config
        if self.device == "cpu":
            kwargs["enable_mkldnn"] = self.enable_mkldnn
            kwargs["cpu_threads"] = self.cpu_threads

        engine = engine_class(**kwargs)
        logger.info(
            "paddleocr_engine_ready",
            pipeline="PaddleOCR",
            device=self.device,
            precision=self.precision,
            using_custom_config=bool(paddlex_config),
        )
        return engine

    def _get_engine(self) -> Any:
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def ocr(self, image_bytes: bytes) -> dict[str, Any]:
        engine = self._get_engine()
        prediction = _first_prediction(engine.predict(_image_bytes_to_array(image_bytes)))
        payload = _extract_text_payload(prediction)
        return {"results": [_build_local_ocr_result(payload)]}


class LocalPPStructureClient:
    def __init__(
        self,
        *,
        device: ResolvedOCRDevice,
        precision: str,
        cpu_threads: int,
        enable_mkldnn: bool,
        local_model_dir: str | None,
    ) -> None:
        self.device = device
        self.precision = _effective_precision(device, precision)
        self.cpu_threads = cpu_threads
        self.enable_mkldnn = enable_mkldnn
        self.local_model_dir = local_model_dir
        self._engine: Any | None = None

    def _build_engine(self) -> Any:
        paddleocr_module = _import_paddleocr_module()
        engine_class = getattr(paddleocr_module, "PPStructureV3", None)
        if engine_class is None:
            raise RuntimeError("paddleocr.PPStructureV3 is not available")

        paddlex_config = _resolve_paddlex_config(
            self.local_model_dir, "PP-StructureV3.yaml"
        )
        kwargs: dict[str, Any] = {
            "device": self.device,
            "precision": self.precision,
        }
        if paddlex_config:
            kwargs["paddlex_config"] = paddlex_config
        if self.device == "cpu":
            kwargs["enable_mkldnn"] = self.enable_mkldnn
            kwargs["cpu_threads"] = self.cpu_threads

        engine = engine_class(**kwargs)
        logger.info(
            "paddleocr_engine_ready",
            pipeline="PPStructureV3",
            device=self.device,
            precision=self.precision,
            using_custom_config=bool(paddlex_config),
        )
        return engine

    def _get_engine(self) -> Any:
        if self._engine is None:
            self._engine = self._build_engine()
        return self._engine

    def ocr(self, image_bytes: bytes) -> dict[str, Any]:
        engine = self._get_engine()
        prediction = _first_prediction(engine.predict(_image_bytes_to_array(image_bytes)))
        payload = _extract_structure_payload(prediction)
        pruned_result = _to_plain_value(payload.get("prunedResult") or {})
        layout_result: dict[str, Any] = {"prunedResult": pruned_result}
        markdown = _normalize_markdown(payload.get("markdown"))
        if markdown is not None:
            layout_result["markdown"] = markdown

        overall_ocr_result = (
            pruned_result.get("overall_ocr_res")
            if isinstance(pruned_result, dict)
            else None
        )
        base_result = (
            _build_local_ocr_result(overall_ocr_result)
            if isinstance(overall_ocr_result, dict)
            else {"rec_texts": [], "rec_scores": [], "dt_polys": []}
        )
        base_result["layoutParsingResults"] = [layout_result]
        return {"results": [base_result]}


__all__ = [
    "LocalPaddleOCRClient",
    "LocalPPStructureClient",
    "ensure_local_runtime_available",
    "resolve_device",
]
