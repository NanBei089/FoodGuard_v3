from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path


class ExportOnnxScriptTests(unittest.TestCase):
    def test_default_weights_points_to_tuned_obb_best_checkpoint(self) -> None:
        module = importlib.import_module("export_onnx")

        self.assertEqual(
            module.DEFAULT_WEIGHTS,
            Path("runs/obb/runs/train_tuned/yolo26s-obb-geo-tuned/weights/best.pt"),
        )

    def test_resolve_export_settings_uses_run_metadata_for_imgsz_and_output_name(self) -> None:
        module = importlib.import_module("export_onnx")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            weights = root / "runs" / "obb" / "runs" / "train_tuned" / "yolo26s-obb-geo-tuned" / "weights" / "best.pt"
            weights.parent.mkdir(parents=True)
            weights.write_text("stub", encoding="utf-8")
            (weights.parent.parent / "args.yaml").write_text(
                "imgsz: 1024\nname: yolo26s-obb-geo-tuned\n",
                encoding="utf-8",
            )

            settings = module.resolve_export_settings(weights)

        self.assertEqual(settings["imgsz"], 1024)
        self.assertEqual(
            settings["output"],
            weights.parent / "yolo26s-obb-geo-tuned.onnx",
        )

    def test_parse_args_allows_manual_weight_switch(self) -> None:
        module = importlib.import_module("export_onnx")

        args = module.parse_args(
            [
                "--weights",
                "runs/obb/runs/train/yolo26s-obb-coordatt/weights/best.pt",
                "--imgsz",
                "640",
            ]
        )

        self.assertEqual(
            args.weights,
            Path("runs/obb/runs/train/yolo26s-obb-coordatt/weights/best.pt"),
        )
        self.assertEqual(args.imgsz, 640)

    def test_load_yolo_model_registers_custom_modules_and_sets_obb_task(self) -> None:
        module = importlib.import_module("export_onnx")
        calls: list[tuple[str, str | None]] = []

        class FakeYOLO:
            def __init__(self, model_name: str, task: str | None = None) -> None:
                calls.append(("init", model_name))
                calls.append(("task", task))

        model = module.load_yolo_model(
            Path("runs/obb/runs/train/yolo26s-obb-coordatt/weights/best.pt"),
            yolo_cls=FakeYOLO,
            register_modules=lambda: calls.append(("register", None)),
        )

        self.assertIsInstance(model, FakeYOLO)
        self.assertEqual(
            calls,
            [
                ("register", None),
                ("init", "runs\\obb\\runs\\train\\yolo26s-obb-coordatt\\weights\\best.pt"),
                ("task", "obb"),
            ],
        )

    def test_export_model_renames_generated_best_onnx_to_run_name(self) -> None:
        module = importlib.import_module("export_onnx")

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            weights = root / "runs" / "obb" / "runs" / "train" / "yolo26s-obb-p2" / "weights" / "best.pt"
            weights.parent.mkdir(parents=True)
            weights.write_text("stub", encoding="utf-8")
            (weights.parent.parent / "args.yaml").write_text(
                "imgsz: 640\nname: yolo26s-obb-p2\n",
                encoding="utf-8",
            )

            exported = weights.with_suffix(".onnx")
            exported.write_text("onnx", encoding="utf-8")

            class FakeModel:
                def export(self, **kwargs):
                    return str(exported)

            output = module.export_model(
                weights=weights,
                model=FakeModel(),
                imgsz=None,
                output=None,
            )

            self.assertEqual(output, weights.parent / "yolo26s-obb-p2.onnx")
            self.assertTrue(output.exists())
            self.assertFalse(exported.exists())


if __name__ == "__main__":
    unittest.main()
