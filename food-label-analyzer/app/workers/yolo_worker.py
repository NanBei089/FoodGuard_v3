"""YOLO 相关工具，负责找营养成分表、裁剪图片和遮罩图片。"""


from __future__ import annotations

import importlib.util
import io
import math
import threading
from pathlib import Path
from typing import Any, Sequence

import structlog
from PIL import Image
from ultralytics import YOLO

from app.core.config import get_settings

logger = structlog.get_logger(__name__)

TABLE_NUM = 0


def _ensure_file(path: str | Path, label: str) -> Path:
    """确认给定路径确实是一个存在的文件。"""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"{label}不存在: {file_path}")
    if not file_path.is_file():
        raise FileNotFoundError(f"{label}不是有效文件: {file_path}")
    return file_path


def _clamp_bbox(raw_xyxy: Sequence[float], img_w: int, img_h: int) -> list[int]:
    """把检测框限制在图片尺寸范围内。"""
    if len(raw_xyxy) != 4:
        raise ValueError(f"bbox 长度必须为 4，当前为 {len(raw_xyxy)}")

    x1 = max(0, min(int(math.floor(raw_xyxy[0])), img_w))
    y1 = max(0, min(int(math.floor(raw_xyxy[1])), img_h))
    x2 = max(0, min(int(math.ceil(raw_xyxy[2])), img_w))
    y2 = max(0, min(int(math.ceil(raw_xyxy[3])), img_h))
    return [x1, y1, x2, y2]


def _bbox_area(xyxy: Sequence[int]) -> int:
    """计算检测框面积。"""
    width = max(0, xyxy[2] - xyxy[0])
    height = max(0, xyxy[3] - xyxy[1])
    return width * height


def detect_nutrition_bbox(
    model: YOLO,
    model_path: str | Path,
    image_path: str | Path,
    conf: float = 0.25,
    imgsz: int = 640,
    select_top_k: int = 5,
) -> dict[str, Any]:
    """用给定 YOLO 模型检测图片里的营养成分表。"""
    model_file = _ensure_file(model_path, "模型文件")
    image_file = _ensure_file(image_path, "图片文件")

    try:
        results = model.predict(
            source=str(image_file),
            imgsz=imgsz,
            conf=conf,
            verbose=False,
        )
    except Exception as exc:
        raise RuntimeError(
            f"YOLO 推理失败，请检查模型或图片是否可用。模型: {model_file}，图片: {image_file}"
        ) from exc

    if not results:
        raise RuntimeError("YOLO 未返回任何结果。")

    result = results[0]
    if not hasattr(result, "orig_shape") or result.orig_shape is None:
        raise RuntimeError("YOLO 结果缺少原图尺寸信息。")

    img_h, img_w = int(result.orig_shape[0]), int(result.orig_shape[1])
    boxes = _prediction_boxes(result)

    response: dict[str, Any] = {
        "found": False,
        "image_path": image_file.resolve().as_posix(),
        "model_path": model_file.resolve().as_posix(),
        "img_w": img_w,
        "img_h": img_h,
        "candidates": [],
        "selected": None,
    }

    if boxes is None or len(boxes) == 0:
        return response

    xyxy_list = boxes.xyxy.cpu().tolist()
    conf_list = (
        boxes.conf.cpu().tolist() if boxes.conf is not None else [0.0] * len(xyxy_list)
    )
    cls_list = (
        boxes.cls.cpu().tolist()
        if boxes.cls is not None
        else [TABLE_NUM] * len(xyxy_list)
    )

    candidates: list[dict[str, Any]] = []
    for xyxy, score, cls_id in zip(xyxy_list, conf_list, cls_list):
        if int(round(cls_id)) != TABLE_NUM:
            continue

        clamped_xyxy = _clamp_bbox(xyxy, img_w=img_w, img_h=img_h)
        area = _bbox_area(clamped_xyxy)
        if area <= 0:
            continue

        candidates.append(
            {
                "xyxy": clamped_xyxy,
                "conf": float(score),
                "area": area,
            }
        )

    if not candidates:
        return response

    candidates.sort(key=lambda item: item["conf"], reverse=True)
    top_candidates = candidates[:select_top_k]

    if len(candidates) == 1:
        selected = candidates[0]
    else:
        selected = max(top_candidates, key=lambda item: (item["area"], item["conf"]))

    response["found"] = True
    response["candidates"] = candidates
    response["selected"] = selected
    return response


def detect_nutrition_bbox_from_results(
    results: Any,
    select_top_k: int = 5,
) -> dict[str, Any]:
    """把 YOLO 原始结果整理成统一的检测框结果。"""
    response: dict[str, Any] = {
        "found": False,
        "image_path": "",
        "model_path": "",
        "img_w": 0,
        "img_h": 0,
        "candidates": [],
        "selected": None,
    }

    if not results:
        return response

    result = results[0]
    if not hasattr(result, "orig_shape") or result.orig_shape is None:
        raise RuntimeError("YOLO 结果缺少原图尺寸信息。")

    img_h, img_w = int(result.orig_shape[0]), int(result.orig_shape[1])
    response["img_w"] = img_w
    response["img_h"] = img_h

    boxes = _prediction_boxes(result)
    if boxes is None or len(boxes) == 0:
        return response

    xyxy_list = boxes.xyxy.cpu().tolist()
    conf_list = (
        boxes.conf.cpu().tolist() if boxes.conf is not None else [0.0] * len(xyxy_list)
    )
    cls_list = (
        boxes.cls.cpu().tolist()
        if boxes.cls is not None
        else [TABLE_NUM] * len(xyxy_list)
    )

    candidates: list[dict[str, Any]] = []
    for xyxy, score, cls_id in zip(xyxy_list, conf_list, cls_list):
        if int(round(cls_id)) != TABLE_NUM:
            continue

        clamped_xyxy = _clamp_bbox(xyxy, img_w=img_w, img_h=img_h)
        area = _bbox_area(clamped_xyxy)
        if area <= 0:
            continue

        candidates.append(
            {
                "xyxy": clamped_xyxy,
                "conf": float(score),
                "area": area,
            }
        )

    if not candidates:
        return response

    candidates.sort(key=lambda item: item["conf"], reverse=True)
    top_candidates = candidates[:select_top_k]
    selected = max(top_candidates, key=lambda item: (item["area"], item["conf"]))

    response["found"] = True
    response["candidates"] = candidates
    response["selected"] = selected
    return response


def _prediction_boxes(result: Any) -> Any:
    """优先读取 OBB 旋转框结果，没有时再读取普通检测框。"""
    obb = getattr(result, "obb", None)
    if obb is not None and len(obb) > 0 and getattr(obb, "xyxy", None) is not None:
        return obb
    boxes = getattr(result, "boxes", None)
    if boxes is not None and len(boxes) > 0:
        return boxes
    return None


def _model_task_for_path(model_path: str | Path) -> str:
    """根据模型文件名判断应该按普通检测还是 OBB 检测加载。"""
    return "obb" if "obb" in Path(model_path).stem.lower() else "detect"


_MODEL_INSTANCE: YOLO | None = None
_model_lock = threading.Lock()


def _get_model() -> YOLO:
    """懒加载 YOLO 模型，避免每次请求都重新加载。"""
    global _MODEL_INSTANCE
    if _MODEL_INSTANCE is None:
        with _model_lock:
            if _MODEL_INSTANCE is None:
                settings = get_settings()
                model_path = settings.YOLO_MODEL_PATH
                if (
                    Path(model_path).suffix.lower() == ".onnx"
                    and importlib.util.find_spec("onnx") is None
                ):
                    raise RuntimeError(
                        "onnx package is required for YOLO ONNX models but is not installed"
                    )
                _MODEL_INSTANCE = YOLO(model_path, task=_model_task_for_path(model_path))
    return _MODEL_INSTANCE


def warmup() -> None:
    settings = get_settings()
    model = _get_model()
    dummy_image = Image.new(
        "RGB",
        (settings.YOLO_INPUT_SIZE, settings.YOLO_INPUT_SIZE),
        color=(128, 128, 128),
    )
    results = model.predict(
        source=dummy_image, imgsz=settings.YOLO_INPUT_SIZE, verbose=False
    )
    detect_nutrition_bbox_from_results(results, select_top_k=1)


def _selected_result_to_bbox(result: dict[str, Any]) -> dict[str, int | float] | None:
    """把内部检测结果转成简单的 bbox 字典。"""
    if result["found"] and result["selected"] is not None:
        xyxy = result["selected"]["xyxy"]
        return {
            "x1": xyxy[0],
            "y1": xyxy[1],
            "x2": xyxy[2],
            "y2": xyxy[3],
            "confidence": result["selected"]["conf"],
        }
    return None


def _bbox_from_model_result(
    result: Any, select_top_k: int
) -> dict[str, int | float] | None:
    """从单张图片的模型结果里取出最终检测框。"""
    try:
        parsed = detect_nutrition_bbox_from_results(
            [result],
            select_top_k=select_top_k,
        )
        return _selected_result_to_bbox(parsed)
    except Exception as exc:
        logger.warning("yolo_result_parse_failed", error=str(exc))
        return None


def detect_many(
    image_bytes_list: Sequence[bytes], conf: float | None = None
) -> list[dict[str, int | float] | None]:
    """批量检测图片里的营养成分表位置。"""
    settings = get_settings()
    if conf is None:
        conf = settings.YOLO_CONFIDENCE_THRESHOLD

    detections: list[dict[str, int | float] | None] = [None] * len(image_bytes_list)
    if not image_bytes_list:
        return detections

    try:
        model = _get_model()
        valid_images: list[Image.Image] = []
        valid_indices: list[int] = []
        for index, image_bytes in enumerate(image_bytes_list):
            try:
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            except (OSError, ValueError) as exc:
                logger.warning("yolo_image_decode_failed", index=index, error=str(exc))
                continue
            valid_images.append(image)
            valid_indices.append(index)

        if not valid_images:
            return detections

        try:
            results = model.predict(
                source=valid_images,
                imgsz=settings.YOLO_INPUT_SIZE,
                conf=conf,
                verbose=False,
            )
            for batch_index, result in enumerate(
                list(results or [])[: len(valid_images)]
            ):
                detections[valid_indices[batch_index]] = _bbox_from_model_result(
                    result,
                    settings.YOLO_SELECT_TOP_K,
                )
            return detections
        except Exception:
            import os
            import tempfile

            temp_paths: list[str] = []
            try:
                for image in valid_images:
                    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                        temp_paths.append(tmp.name)
                    image.save(temp_paths[-1], format="JPEG")

                results = model.predict(
                    source=temp_paths,
                    conf=conf,
                    imgsz=settings.YOLO_INPUT_SIZE,
                    verbose=False,
                )
                for batch_index, result in enumerate(
                    list(results or [])[: len(temp_paths)]
                ):
                    detections[valid_indices[batch_index]] = _bbox_from_model_result(
                        result,
                        settings.YOLO_SELECT_TOP_K,
                    )
            finally:
                for temp_path in temp_paths:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)

        return detections
    except Exception as exc:
        logger.warning("yolo_detect_failed", error=str(exc))
        return detections


def detect(
    image_bytes: bytes, conf: float | None = None
) -> dict[str, int | float] | None:
    """检测单张图片里的营养成分表位置。"""
    return detect_many([image_bytes], conf=conf)[0]


def crop_image(image_bytes: bytes, bbox: dict, padding: int | None = None) -> bytes:
    """按检测框把营养成分表裁出来。"""
    if padding is None:
        settings = get_settings()
        padding = settings.YOLO_CROP_PADDING
    import io

    from PIL import Image

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    crop_x1 = max(0, int(bbox["x1"]) - padding)
    crop_y1 = max(0, int(bbox["y1"]) - padding)
    crop_x2 = min(width, int(bbox["x2"]) + padding)
    crop_y2 = min(height, int(bbox["y2"]) + padding)

    cropped = image.crop((crop_x1, crop_y1, crop_x2, crop_y2))
    buffer = io.BytesIO()
    cropped.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


def mask_image(image_bytes: bytes, bbox: dict, padding: int | None = None) -> bytes:
    """把原图中的营养成分表区域盖白。"""
    if padding is None:
        settings = get_settings()
        padding = settings.YOLO_CROP_PADDING
    import io

    from PIL import Image, ImageDraw

    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    width, height = image.size

    crop_x1 = max(0, int(bbox["x1"]) - padding)
    crop_y1 = max(0, int(bbox["y1"]) - padding)
    crop_x2 = min(width, int(bbox["x2"]) + padding)
    crop_y2 = min(height, int(bbox["y2"]) + padding)

    masked = image.copy()
    draw = ImageDraw.Draw(masked)
    draw.rectangle([crop_x1, crop_y1, crop_x2, crop_y2], fill=(255, 255, 255))
    buffer = io.BytesIO()
    masked.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()


__all__ = [
    "detect",
    "detect_many",
    "detect_nutrition_bbox",
    "crop_image",
    "mask_image",
    "warmup",
    "_get_model",
]
