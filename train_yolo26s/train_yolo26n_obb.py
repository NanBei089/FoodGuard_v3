from __future__ import annotations

from typing import Any

from train_yolo26s_obb import train_yolo_obb


def build_default_config() -> dict[str, Any]:
    """Return the default training config for the lightweight YOLO26n-OBB comparison."""

    return {
        "model_name": "yolo26n-obb.pt",
        "task": "obb",
        "data_yaml": "./dataset/dataset.yaml",
        "batch_size": -1,
        "epochs": 180,
        "img_size": 640,
        "device": 0,
        "workers": 4,
        "run_name": "yolo26n-obb-light",
        "project": "runs/train",
    }


def main() -> None:
    """PyCharm direct-run entrypoint."""

    train_yolo_obb(build_default_config())


if __name__ == "__main__":
    main()
