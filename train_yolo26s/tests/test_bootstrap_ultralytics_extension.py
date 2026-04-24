from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class BootstrapUltralyticsExtensionTests(unittest.TestCase):
    def test_patch_modules_init_adds_doc_import_without_corrupting_existing_import(self) -> None:
        from tools.bootstrap_ultralytics_extension import patch_modules_init

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_path = root / "ultralytics" / "nn" / "modules" / "__init__.py"
            init_path.parent.mkdir(parents=True)
            init_path.write_text(
                'from .conv import (\n    Concat,\n    Conv,\n)\n\n__all__ = (\n    "C3k2",\n)\n',
                encoding="utf-8",
            )

            patch_modules_init(root)
            text = init_path.read_text(encoding="utf-8")

        self.assertIn("from .conv import (\n    Concat,\n    Conv,\n)", text)
        self.assertIn("from .doc import CoordAttLite, DocC3k2, DocFReLU, ScaledResidual", text)
        self.assertIn('"CoordAttLite"', text)
        self.assertNotIn("importfrom", text)
        self.assertNotIn("from .conv import (\nfrom .doc", text)

    def test_patch_tasks_adds_custom_modules_to_import_and_parse_sets(self) -> None:
        from tools.bootstrap_ultralytics_extension import patch_tasks

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tasks_path = root / "ultralytics" / "nn" / "tasks.py"
            tasks_path.parent.mkdir(parents=True)
            tasks_path.write_text(
                "from ultralytics.nn.modules import (\n"
                "    C3k2,\n"
                ")\n"
                "def parse_model():\n"
                "    base_modules = frozenset(\n"
                "        {\n"
                "            C3k2,\n"
                "        }\n"
                "    )\n"
                "    repeat_modules = frozenset(\n"
                "        {\n"
                "            C3k2,\n"
                "        }\n"
                "    )\n",
                encoding="utf-8",
            )

            patch_tasks(root)
            text = tasks_path.read_text(encoding="utf-8")

        self.assertIn("CoordAttLite", text)
        self.assertEqual(text.count("DocC3k2"), 3)
        self.assertIn("            CoordAttLite,\n            DocC3k2,\n", text)


if __name__ == "__main__":
    unittest.main()
