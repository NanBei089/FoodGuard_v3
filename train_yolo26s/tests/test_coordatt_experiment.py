from __future__ import annotations

import importlib
import importlib.util
import sys
import types
import unittest
from pathlib import Path

import yaml


class CoordAttentionModuleTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("torch"), "torch is not installed")
    def test_coordatt_preserves_tensor_shape(self) -> None:
        import torch

        from ultralytics_ext.coordatt import CoordAtt

        block = CoordAtt(128)
        x = torch.randn(2, 128, 32, 32)

        y = block(x)

        self.assertEqual(tuple(y.shape), (2, 128, 32, 32))

    @unittest.skipUnless(importlib.util.find_spec("torch"), "torch is not installed")
    def test_residual_coordatt_starts_as_identity_mapping(self) -> None:
        import torch

        from ultralytics_ext.coordatt import ResidualCoordAtt

        block = ResidualCoordAtt(128)
        x = torch.randn(2, 128, 32, 32)

        y = block(x)

        self.assertTrue(torch.allclose(y, x))

    def test_register_custom_modules_adds_coordatt_to_ultralytics_tasks(self) -> None:
        fake_torch = types.ModuleType("torch")
        fake_nn = types.ModuleType("torch.nn")

        class FakeModule:
            pass

        class FakeLayer(FakeModule):
            def __init__(self, *args, **kwargs) -> None:
                pass

        fake_nn.Module = FakeModule
        fake_nn.AdaptiveAvgPool2d = FakeLayer
        fake_nn.Conv2d = FakeLayer
        fake_nn.BatchNorm2d = FakeLayer
        fake_nn.SiLU = FakeLayer
        fake_torch.nn = fake_nn

        fake_ultralytics = types.ModuleType("ultralytics")
        fake_ultralytics_nn = types.ModuleType("ultralytics.nn")
        fake_tasks = types.ModuleType("ultralytics.nn.tasks")

        previous = {
            name: sys.modules.get(name)
            for name in (
                "torch",
                "torch.nn",
                "ultralytics",
                "ultralytics.nn",
                "ultralytics.nn.tasks",
                "ultralytics_ext.coordatt",
                "ultralytics_ext.register",
            )
        }

        try:
            sys.modules["torch"] = fake_torch
            sys.modules["torch.nn"] = fake_nn
            sys.modules["ultralytics"] = fake_ultralytics
            sys.modules["ultralytics.nn"] = fake_ultralytics_nn
            sys.modules["ultralytics.nn.tasks"] = fake_tasks
            sys.modules.pop("ultralytics_ext.coordatt", None)
            sys.modules.pop("ultralytics_ext.register", None)

            register = importlib.import_module("ultralytics_ext.register")
            coordatt = importlib.import_module("ultralytics_ext.coordatt")

            register.register_custom_modules()

            self.assertIs(fake_tasks.CoordAtt, coordatt.CoordAtt)
            self.assertIs(fake_tasks.ResidualCoordAtt, coordatt.ResidualCoordAtt)
        finally:
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


class CoordAttentionExperimentTests(unittest.TestCase):
    def test_model_yaml_inserts_three_coordatt_layers_before_obb_head(self) -> None:
        cfg = yaml.safe_load(Path("models/yolo26s-obb-coordatt.yaml").read_text(encoding="utf-8"))

        coordatt_layers = [layer for layer in cfg["head"] if layer[2] == "CoordAtt"]

        self.assertEqual(cfg["nc"], 1)
        self.assertEqual(coordatt_layers, [[16, 1, "CoordAtt", [128]], [20, 1, "CoordAtt", [256]], [24, 1, "CoordAtt", [512]]])
        self.assertEqual(cfg["head"][-1], [[17, 21, 25], 1, "OBB26", ["nc", 1]])

    def test_p3_residual_model_yaml_adds_one_identity_safe_attention_layer(self) -> None:
        cfg = yaml.safe_load(Path("models/yolo26s-obb-rescoordatt-p3.yaml").read_text(encoding="utf-8"))

        residual_layers = [layer for layer in cfg["head"] if layer[2] == "ResidualCoordAtt"]

        self.assertEqual(cfg["nc"], 1)
        self.assertEqual(residual_layers, [[16, 1, "ResidualCoordAtt", [128]]])
        self.assertEqual(cfg["head"][-1], [[23, 19, 22], 1, "OBB26", ["nc", 1]])

    def test_default_config_uses_coordatt_experiment_settings(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_coordatt")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "models/yolo26s-obb-coordatt.yaml")
        self.assertEqual(config["pretrained_weights"], "yolo26s-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 640)
        self.assertEqual(config["batch_size"], -1)
        self.assertEqual(config["run_name"], "yolo26s-obb-coordatt")
        self.assertEqual(config["project"], "runs/train")

    def test_load_yolo_model_registers_modules_and_loads_pretrained_weights(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_coordatt")
        calls: list[tuple[str, str | None]] = []

        class FakeYOLO:
            def __init__(self, model_name: str, task: str | None = None) -> None:
                calls.append(("init", model_name))
                calls.append(("task", task))

            def load(self, weights: str):
                calls.append(("load", weights))
                return self

        model = module.load_yolo_model(
            "models/yolo26s-obb-coordatt.yaml",
            pretrained_weights="yolo26s-obb.pt",
            yolo_cls=FakeYOLO,
            register_modules=lambda: calls.append(("register", None)),
        )

        self.assertIsInstance(model, FakeYOLO)
        self.assertEqual(
            calls,
            [
                ("register", None),
                ("init", "models/yolo26s-obb-coordatt.yaml"),
                ("task", "obb"),
                ("load", "yolo26s-obb.pt"),
            ],
        )

    def test_default_config_uses_p3_residual_attention_settings(self) -> None:
        module = importlib.import_module("train_yolo26s_obb_rescoordatt_p3")

        config = module.build_default_config()

        self.assertEqual(config["model_name"], "models/yolo26s-obb-rescoordatt-p3.yaml")
        self.assertEqual(config["pretrained_weights"], "yolo26s-obb.pt")
        self.assertEqual(config["task"], "obb")
        self.assertEqual(config["data_yaml"], "./dataset/dataset.yaml")
        self.assertEqual(config["epochs"], 180)
        self.assertEqual(config["img_size"], 640)
        self.assertEqual(config["batch_size"], -1)
        self.assertEqual(config["run_name"], "yolo26s-obb-rescoordatt-p3")
        self.assertEqual(config["project"], "runs/train")


if __name__ == "__main__":
    unittest.main()
