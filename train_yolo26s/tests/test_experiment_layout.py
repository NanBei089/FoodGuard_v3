from __future__ import annotations

import unittest
import importlib
from pathlib import Path


class ExperimentLayoutTests(unittest.TestCase):
    def test_expected_experiment_entrypoints_exist(self) -> None:
        expected = [
            "train_00_yolo26n_obb_official.py",
            "train_01_yolo26s_obb_official.py",
            "train_02_yolo26s_obb_p2.py",
            "train_03_yolo26s_obb_docres_act.py",
            "train_04_yolo26s_obb_doc_final.py",
            "train_05_ablate_no_p2.py",
            "train_06_ablate_no_docblock.py",
            "train_07_ablate_no_attention.py",
        ]

        for name in expected:
            self.assertTrue((Path("experiments") / name).exists(), name)

    def test_experiment_entrypoints_expose_direct_run_config(self) -> None:
        modules = [
            "experiments.train_00_yolo26n_obb_official",
            "experiments.train_01_yolo26s_obb_official",
            "experiments.train_02_yolo26s_obb_p2",
            "experiments.train_03_yolo26s_obb_docres_act",
            "experiments.train_04_yolo26s_obb_doc_final",
            "experiments.train_05_ablate_no_p2",
            "experiments.train_06_ablate_no_docblock",
            "experiments.train_07_ablate_no_attention",
        ]

        for module_name in modules:
            module = importlib.import_module(module_name)
            self.assertTrue(hasattr(module, "build_config"), module_name)
            self.assertTrue(hasattr(module, "PYCHARM_SMOKE_TEST"), module_name)
            self.assertTrue(hasattr(module, "EXPERIMENT_KEY"), module_name)

    def test_custom_model_yaml_files_exist(self) -> None:
        expected = [
            "yolo26s-obb-p2.yaml",
            "yolo26s-obb-docres-act.yaml",
            "yolo26s-obb-doc-final.yaml",
            "yolo26s-obb-doc-no-p2.yaml",
            "yolo26s-obb-no-docblock.yaml",
            "yolo26s-obb-doc-no-attention.yaml",
        ]

        for name in expected:
            path = Path("models") / name
            self.assertTrue(path.exists(), name)
            text = path.read_text(encoding="utf-8")
            self.assertIn("OBB26", text)


if __name__ == "__main__":
    unittest.main()
