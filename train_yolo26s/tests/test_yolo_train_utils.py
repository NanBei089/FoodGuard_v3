from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class YoloTrainUtilsTests(unittest.TestCase):
    def test_default_training_kwargs_match_obb_experiment_contract(self) -> None:
        from common.yolo_train_utils import PROJECT_ROOT, TrainingConfig, build_train_kwargs

        cfg = TrainingConfig(
            model_spec="models/custom.yaml",
            run_name="unit-run",
            data_yaml="dataset/dataset.yaml",
        )

        kwargs = build_train_kwargs(cfg)

        self.assertEqual(kwargs["data"], "dataset/dataset.yaml")
        self.assertEqual(kwargs["epochs"], 120)
        self.assertEqual(kwargs["imgsz"], 1024)
        self.assertEqual(kwargs["name"], "unit-run")
        self.assertEqual(kwargs["project"], str(PROJECT_ROOT / "runs" / "obb_experiments"))
        self.assertEqual(kwargs["lr0"], 0.001)
        self.assertEqual(kwargs["mosaic"], 0.5)
        self.assertEqual(kwargs["degrees"], 15.0)
        self.assertEqual(kwargs["perspective"], 0.0005)
        self.assertEqual(kwargs["erasing"], 0.0)

    def test_resolve_data_yaml_falls_back_to_dataset_yaml(self) -> None:
        from common.yolo_train_utils import resolve_data_yaml

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fallback = root / "dataset" / "dataset.yaml"
            fallback.parent.mkdir()
            fallback.write_text("names: [nutrition_table]\n", encoding="utf-8")

            resolved = resolve_data_yaml(root / "missing.yaml", project_root=root)

        self.assertEqual(resolved, fallback)

    def test_training_config_accepts_overrides_without_mutating_defaults(self) -> None:
        from common.yolo_train_utils import TrainingConfig, build_train_kwargs

        cfg = TrainingConfig(
            model_spec="yolo26s-obb.pt",
            run_name="override-run",
            data_yaml="dataset/dataset.yaml",
            epochs=1,
            img_size=640,
            batch_size=2,
            extra_train_args={"seed": 7, "mosaic": 0.0},
        )

        kwargs = build_train_kwargs(cfg)

        self.assertEqual(kwargs["epochs"], 1)
        self.assertEqual(kwargs["imgsz"], 640)
        self.assertEqual(kwargs["batch"], 2)
        self.assertEqual(kwargs["seed"], 7)
        self.assertEqual(kwargs["mosaic"], 0.0)

    def test_apply_pycharm_smoke_test_overrides_safe_defaults(self) -> None:
        from common.yolo_train_utils import TrainingConfig, apply_pycharm_smoke_test

        cfg = TrainingConfig(
            model_spec="yolo26s-obb.pt",
            run_name="unit",
            data_yaml="dataset/dataset.yaml",
        )

        smoke = apply_pycharm_smoke_test(cfg, enabled=True)

        self.assertEqual(smoke.run_name, "unit_smoke")
        self.assertEqual(smoke.epochs, 1)
        self.assertEqual(smoke.img_size, 640)
        self.assertEqual(smoke.batch_size, 2)
        self.assertFalse(smoke.enable_tf_monitor)


if __name__ == "__main__":
    unittest.main()
