from __future__ import annotations

import importlib
import unittest
from pathlib import Path

import yaml


class LightweightObbExperimentTests(unittest.TestCase):
    def test_yolo26n_default_config_uses_lightweight_obb_settings(self) -> None:
        module = importlib.import_module("train_yolo26n_obb")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "yolo26n-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 640)
        self.assertEqual(config["batch_size"], -1)
        self.assertEqual(config["run_name"], "yolo26n-obb-light")
        self.assertEqual(config["project"], "runs/train")


class P2ObbExperimentTests(unittest.TestCase):
    def test_p2_model_yaml_adds_high_resolution_obb_detection_input(self) -> None:
        cfg = yaml.safe_load(Path("models/yolo26s-obb-p2.yaml").read_text(encoding="utf-8"))

        self.assertEqual(cfg["nc"], 1)
        self.assertEqual(cfg["head"][-4], [16, 1, "nn.Upsample", ["None", 2, "nearest"]])
        self.assertEqual(cfg["head"][-3], [[-1, 2], 1, "Concat", [1]])
        self.assertEqual(cfg["head"][-2], [-1, 2, "C3k2", [128, True]])
        self.assertEqual(cfg["head"][-1], [[25, 16, 19, 22], 1, "OBB26", ["nc", 1]])

    def test_p2_default_config_uses_custom_model_and_baseline_weights(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_p2")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "models/yolo26s-obb-p2.yaml")
        self.assertEqual(config["pretrained_weights"], "yolo26s-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 640)
        self.assertEqual(config["batch_size"], -1)
        self.assertEqual(config["run_name"], "yolo26s-obb-p2")
        self.assertEqual(config["project"], "runs/train")


if __name__ == "__main__":
    unittest.main()
