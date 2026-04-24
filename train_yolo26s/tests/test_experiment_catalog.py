from __future__ import annotations

import unittest


class ExperimentCatalogTests(unittest.TestCase):
    def test_catalog_lists_all_comparison_experiments_in_training_order(self) -> None:
        from common.experiment_catalog import EXPERIMENTS

        self.assertEqual(
            list(EXPERIMENTS),
            [
                "00_yolo26n_obb_official",
                "01_yolo26s_obb_official",
                "02_yolo26s_obb_p2",
                "03_yolo26s_obb_docres_act",
                "04_yolo26s_obb_doc_final",
                "05_ablate_no_p2",
                "06_ablate_no_docblock",
                "07_ablate_no_attention",
            ],
        )

    def test_catalog_builds_smoke_and_formal_configs(self) -> None:
        from common.experiment_catalog import build_experiment_config

        smoke = build_experiment_config("01_yolo26s_obb_official", smoke_test=True)
        formal = build_experiment_config("01_yolo26s_obb_official", smoke_test=False)

        self.assertEqual(smoke.run_name, "01_yolo26s_obb_official_smoke")
        self.assertEqual(smoke.epochs, 1)
        self.assertEqual(smoke.img_size, 640)
        self.assertEqual(smoke.batch_size, 2)
        self.assertFalse(smoke.enable_tf_monitor)
        self.assertEqual(formal.run_name, "01_yolo26s_obb_official")
        self.assertEqual(formal.epochs, 120)
        self.assertEqual(formal.img_size, 1024)
        self.assertEqual(formal.batch_size, -1)

    def test_catalog_marks_custom_module_experiments(self) -> None:
        from common.experiment_catalog import build_experiment_config

        official = build_experiment_config("01_yolo26s_obb_official", smoke_test=True)
        custom = build_experiment_config("04_yolo26s_obb_doc_final", smoke_test=True)

        self.assertFalse(official.require_custom_modules)
        self.assertTrue(custom.require_custom_modules)


if __name__ == "__main__":
    unittest.main()
