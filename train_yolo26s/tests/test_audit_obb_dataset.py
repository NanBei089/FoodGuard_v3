from __future__ import annotations

import tempfile
import unittest
from pathlib import Path


class AuditObbDatasetTests(unittest.TestCase):
    def test_audit_counts_valid_empty_and_invalid_obb_labels(self) -> None:
        from tools.audit_obb_dataset import audit_dataset

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            label_root = root / "labels"
            (label_root / "train").mkdir(parents=True)
            (label_root / "val").mkdir(parents=True)
            (label_root / "test").mkdir(parents=True)
            (label_root / "train" / "valid.txt").write_text(
                "0 0.1 0.1 0.4 0.1 0.4 0.3 0.1 0.3\n",
                encoding="utf-8",
            )
            (label_root / "train" / "empty.txt").write_text("", encoding="utf-8")
            (label_root / "val" / "bad_columns.txt").write_text(
                "0 0.1 0.1 0.4 0.1\n",
                encoding="utf-8",
            )
            (label_root / "test" / "bad_area.txt").write_text(
                "0 0.1 0.1 0.2 0.2 0.3 0.3 0.4 0.4\n",
                encoding="utf-8",
            )

            summary = audit_dataset(root)

        self.assertEqual(summary.valid_boxes, 1)
        self.assertEqual(summary.empty_label_files, 1)
        self.assertEqual(summary.line_length_counts[9], 2)
        self.assertEqual(summary.line_length_counts[5], 1)
        self.assertEqual(len(summary.errors), 2)
        self.assertIn("expected 9 columns", summary.errors[0].message)
        self.assertIn("zero polygon area", summary.errors[1].message)

    def test_validate_rejects_out_of_range_coordinates(self) -> None:
        from tools.audit_obb_dataset import validate_obb_label_line

        errors = validate_obb_label_line(
            "0 0.1 0.1 1.2 0.1 0.4 0.3 0.1 0.3",
            Path("sample.txt"),
            1,
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("outside [0, 1]", errors[0].message)


if __name__ == "__main__":
    unittest.main()
