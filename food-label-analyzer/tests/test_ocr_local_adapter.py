from __future__ import annotations

import importlib
import io
from types import SimpleNamespace

import pytest
from PIL import Image

from app.workers.ocr.parsing import _extract_table_from_layout, extract_text_lines
from tests.conftest import load_required_env


def _image_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color=(255, 255, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_resolve_device_auto_falls_back_to_cpu_when_paddle_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch, PADDLEOCR_MODE="local")
    local_module = importlib.reload(
        importlib.import_module("app.workers.ocr.local_engine")
    )
    original_import = importlib.import_module

    def fake_import(name: str):
        if name == "paddle":
            raise ImportError("paddle unavailable")
        return original_import(name)

    monkeypatch.setattr(local_module, "import_module", fake_import)

    assert local_module.resolve_device("auto") == "cpu"


def test_local_paddleocr_client_maps_predict_output_for_text_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch, PADDLEOCR_MODE="local")
    local_module = importlib.reload(
        importlib.import_module("app.workers.ocr.local_engine")
    )

    class FakePaddleOCR:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def predict(self, image):
            assert image.shape == (32, 32, 3)
            return [
                {
                    "res": {
                        "rec_texts": ["配料", "食用盐"],
                        "rec_scores": [0.99, 0.91],
                        "dt_polys": [
                            [[0, 0], [10, 0], [10, 8], [0, 8]],
                            [[0, 12], [16, 12], [16, 20], [0, 20]],
                        ],
                    }
                }
            ]

    monkeypatch.setattr(
        local_module,
        "import_module",
        lambda name: SimpleNamespace(PaddleOCR=FakePaddleOCR)
        if name == "paddleocr"
        else importlib.import_module(name),
    )

    client = local_module.LocalPaddleOCRClient(
        device="cpu",
        precision="fp16",
        cpu_threads=4,
        enable_mkldnn=True,
        use_doc_orientation_classify=True,
        use_doc_unwarping=True,
        use_textline_orientation=True,
        text_det_limit_side_len=960,
        text_det_limit_type="max",
        text_det_thresh=0.3,
        text_det_box_thresh=0.5,
        text_det_unclip_ratio=1.8,
        local_model_dir=None,
    )

    result = client.ocr(_image_bytes())
    lines = extract_text_lines(result)

    assert [line["text"] for line in lines] == ["配料", "食用盐"]
    assert lines[0]["bbox"] == [[0, 0], [10, 0], [10, 8], [0, 8]]


def test_local_ppstructure_client_maps_predict_output_for_table_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_required_env(monkeypatch, PADDLEOCR_MODE="local")
    local_module = importlib.reload(
        importlib.import_module("app.workers.ocr.local_engine")
    )
    table_html = (
        "<table><tr><td>项目</td><td>每100g</td></tr>"
        "<tr><td>能量</td><td>100kJ</td></tr></table>"
    )

    class FakePPStructureV3:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def predict(self, image):
            assert image.shape == (32, 32, 3)
            return [
                {
                    "prunedResult": {
                        "overall_ocr_res": {
                            "rec_texts": ["营养成分表", "能量 100kJ"],
                            "rec_scores": [0.98, 0.95],
                            "dt_polys": [
                                [[0, 0], [10, 0], [10, 8], [0, 8]],
                                [[0, 12], [16, 12], [16, 20], [0, 20]],
                            ],
                        },
                        "parsing_res_list": [
                            {
                                "block_label": "table",
                                "block_content": table_html,
                            }
                        ],
                    },
                    "markdown": {"text": "营养成分表\n能量 100kJ"},
                }
            ]

    monkeypatch.setattr(
        local_module,
        "import_module",
        lambda name: SimpleNamespace(PPStructureV3=FakePPStructureV3)
        if name == "paddleocr"
        else importlib.import_module(name),
    )

    client = local_module.LocalPPStructureClient(
        device="cpu",
        precision="fp16",
        cpu_threads=4,
        enable_mkldnn=True,
        local_model_dir=None,
    )

    result = client.ocr(_image_bytes())
    lines = extract_text_lines(result)
    table_data = _extract_table_from_layout(result["results"][0]["layoutParsingResults"])

    assert [line["text"] for line in lines] == ["营养成分表", "能量 100kJ"]
    assert table_data == {"html": table_html, "source": "layout"}
