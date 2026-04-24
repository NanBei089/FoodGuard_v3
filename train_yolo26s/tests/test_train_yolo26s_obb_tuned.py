from __future__ import annotations

import importlib
import unittest


class TrainYolo26sObbTunedScriptTests(unittest.TestCase):
    def test_default_config_uses_tuned_settings(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_tuned")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "yolo26s-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 1024)
        self.assertEqual(config["device"], 0)
        self.assertEqual(config["workers"], 4)
        self.assertEqual(config["run_name"], "yolo26s-obb-geo-tuned")
        self.assertEqual(config["project"], "runs/train_tuned")
        self.assertEqual(module.PYCHARM_CONDA_ENV, "train_env")

    def test_build_train_overrides_reduces_geometric_disruption(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_tuned")

        overrides = module.build_train_overrides()

        self.assertEqual(overrides["close_mosaic"], 20)
        self.assertEqual(overrides["mosaic"], 0.2)
        self.assertEqual(overrides["erasing"], 0.0)
        self.assertIsNone(overrides["auto_augment"])
        self.assertEqual(overrides["box"], 9.0)
        self.assertEqual(overrides["cls"], 0.25)
        self.assertEqual(overrides["angle"], 1.5)

    def test_load_yolo_model_sets_obb_task(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_tuned")
        captured: dict[str, str | None] = {}

        class FakeYOLO:
            def __init__(self, model_name: str, task: str | None = None) -> None:
                captured["model_name"] = model_name
                captured["task"] = task

        module.load_yolo_model("yolo26s-obb.pt", yolo_cls=FakeYOLO)

        self.assertEqual(captured["model_name"], "yolo26s-obb.pt")
        self.assertEqual(captured["task"], "obb")

    def test_tuned_script_keeps_its_own_progress_callback(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_tuned")

        self.assertEqual(module._register_progress_callback.__module__, "train_yolo26s_obb_tuned")


if __name__ == "__main__":
    unittest.main()
