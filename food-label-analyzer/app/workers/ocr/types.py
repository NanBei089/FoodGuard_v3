from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class OCRConfig:
    job_url: str
    token: str
    model: str = "PaddleOCR-VL-1.5"
    lang: str = "ch"
    use_angle_cls: bool = True
    det: bool = True
    rec: bool = True
    det_db_box_thresh: float = 0.5
    det_db_unclip_ratio: float = 1.8
    rec_char_type: str = "ch"
    device: str = "cpu"

    use_doc_orientation_classify: bool = True
    use_doc_unwarping: bool = True
    use_textline_orientation: bool = True
    use_seal_recognition: bool = False

    use_table_recognition: bool = True
    use_e2e_wired_table_rec_model: bool = False
    use_e2e_wireless_table_rec_model: bool = True

    use_formula_recognition: bool = False
    use_chart_recognition: bool = False

    text_det_limit_side_len: int = 960
    text_det_limit_type: str = "max"
    text_det_thresh: float = 0.3

    poll_interval_s: float = 5.0
    poll_timeout_s: float = 300.0
    request_timeout_s: float = 60.0


@dataclass
class OCRTextResult:
    raw_text: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)
    blocks: list[dict[str, Any]] = field(default_factory=list)
    source: Literal["ocr_runtime"] = "ocr_runtime"
    artifact_json_url: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "lines": self.lines,
            "blocks": self.blocks,
            "source": self.source,
            "artifact_json_url": self.artifact_json_url,
        }


@dataclass
class TableRecognitionResult:
    table_json: dict[str, Any] | None = None
    table_html_url: str | None = None
    table_xlsx_url: str | None = None
    ocr_fallback_text: str | None = None
    source: Literal["ocr_runtime"] = "ocr_runtime"

    def model_dump(self) -> dict[str, Any]:
        return {
            "table_json": self.table_json,
            "table_html_url": self.table_html_url,
            "table_xlsx_url": self.table_xlsx_url,
            "ocr_fallback_text": self.ocr_fallback_text,
            "source": self.source,
        }


@dataclass
class OCRParallelResult:
    full_text: OCRTextResult
    nutrition_table: TableRecognitionResult
