from __future__ import annotations

import importlib
import unittest


class TrainYolo26sObbScriptTests(unittest.TestCase):
    def test_default_config_uses_obb_baseline_settings(self) -> None:
        module = importlib.import_module("train_yolo26s_obb")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "yolo26s-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 640)
        self.assertEqual(config["device"], 0)
        self.assertEqual(config["workers"], 4)
        self.assertEqual(config["run_name"], "yolo26s-obb-baseline")
        self.assertEqual(module.PYCHARM_CONDA_ENV, "train_env")

    def test_load_yolo_model_sets_obb_task(self) -> None:
        module = importlib.import_module("train_yolo26s_obb")
        captured: dict[str, str | None] = {}

        class FakeYOLO:
            def __init__(self, model_name: str, task: str | None = None) -> None:
                captured["model_name"] = model_name
                captured["task"] = task

        module.load_yolo_model("yolo26s-obb.pt", yolo_cls=FakeYOLO)

        self.assertEqual(captured["model_name"], "yolo26s-obb.pt")
        self.assertEqual(captured["task"], "obb")


if __name__ == "__main__":
    unittest.main()
