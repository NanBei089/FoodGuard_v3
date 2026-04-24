from __future__ import annotations

import importlib
import unittest
from pathlib import Path


class PyCharmRuntimeTests(unittest.TestCase):
    def test_resolve_project_path_anchors_relative_paths_to_project_root(self) -> None:
        from common.yolo_train_utils import PROJECT_ROOT, resolve_project_path

        self.assertEqual(resolve_project_path("runs/obb_experiments"), PROJECT_ROOT / "runs" / "obb_experiments")
        self.assertEqual(resolve_project_path(PROJECT_ROOT / "dataset" / "dataset.yaml"), PROJECT_ROOT / "dataset" / "dataset.yaml")

    def test_build_train_kwargs_uses_absolute_project_dir_for_pycharm_cwd(self) -> None:
        from common.yolo_train_utils import PROJECT_ROOT, TrainingConfig, build_train_kwargs

        cfg = TrainingConfig(
            model_spec="yolo26s-obb.pt",
            run_name="unit-pycharm",
            data_yaml="dataset/dataset.yaml",
        )

        kwargs = build_train_kwargs(cfg)

        self.assertEqual(kwargs["project"], str(PROJECT_ROOT / "runs" / "obb_experiments"))

    def test_no_separate_pycharm_runner_file_is_required(self) -> None:
        self.assertFalse(Path("pycharm_run.py").exists())

    def test_experiment_file_default_is_pycharm_smoke_test(self) -> None:
        module = importlib.import_module("experiments.train_01_yolo26s_obb_official")

        cfg = module.build_config()

        self.assertEqual(cfg.run_name, "01_yolo26s_obb_official_smoke")
        self.assertEqual(cfg.epochs, 1)
        self.assertEqual(cfg.img_size, 640)
        self.assertEqual(cfg.batch_size, 2)
        self.assertFalse(cfg.enable_tf_monitor)

    def test_audit_default_dataset_path_uses_project_root(self) -> None:
        from tools.audit_obb_dataset import DEFAULT_DATASET

        self.assertEqual(DEFAULT_DATASET, Path.cwd() / "dataset")


if __name__ == "__main__":
    unittest.main()
