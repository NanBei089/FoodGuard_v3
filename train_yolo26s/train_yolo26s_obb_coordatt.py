from __future__ import annotations

from typing import Any, Callable

from train_yolo26s_obb import (
    PYCHARM_CONDA_ENV,
    _create_tf_writer,
    _register_progress_callback,
    _register_tf_callback,
    _resolve_data_yaml,
    _resolve_device,
)


def build_default_config() -> dict[str, Any]:
    """Return the default training config for the CoordAttention experiment."""

    return {
        "model_name": "models/yolo26s-obb-coordatt.yaml",
        "pretrained_weights": "yolo26s-obb.pt",
        "task": "obb",
        "data_yaml": "./dataset/dataset.yaml",
        "batch_size": -1,
        "epochs": 180,
        "img_size": 640,
        "device": 0,
        "workers": 4,
        "run_name": "yolo26s-obb-coordatt",
        "project": "runs/train",
    }


def load_yolo_model(
    model_name: str,
    pretrained_weights: str | None = None,
    yolo_cls=None,
    register_modules: Callable[[], None] | None = None,
):
    """Load the custom OBB model and transfer matching baseline weights."""

    if register_modules is None:
        from ultralytics_ext.register import register_custom_modules

        register_modules = register_custom_modules

    register_modules()

    if yolo_cls is None:
        try:
            from ultralytics import YOLO
        except ModuleNotFoundError as exc:
            raise RuntimeError("未检测到 ultralytics，请先激活 train_env 并安装 requirements.txt。") from exc

        yolo_cls = YOLO

    model = yolo_cls(model_name, task="obb")
    if pretrained_weights:
        model.load(pretrained_weights)
    return model


def train_yolo_obb(config: dict[str, Any] | None = None) -> None:
    """Train YOLO26s-OBB with CoordAttention using the baseline settings."""

    config = build_default_config() if config is None else config
    model = load_yolo_model(config["model_name"], config.get("pretrained_weights"))

    augmentations = {
        "hsv_h": 0.012,
        "hsv_s": 0.5,
        "hsv_v": 0.3,
        "degrees": 3.0,
        "translate": 0.05,
        "scale": 0.3,
        "shear": 0.0,
        "flipud": 0.0,
        "fliplr": 0.2,
    }

    writer = _create_tf_writer(config["run_name"])
    _register_tf_callback(model, writer)
    _register_progress_callback(model, config["epochs"])

    resolved_data_yaml = _resolve_data_yaml(config["data_yaml"])
    resolved_device = _resolve_device(config["device"])

    try:
        model.train(
            data=resolved_data_yaml,
            epochs=config["epochs"],
            imgsz=config["img_size"],
            batch=config["batch_size"],
            device=resolved_device,
            name=config["run_name"],
            workers=config["workers"],
            save_period=10,
            cache=True,
            optimizer="auto",
            cos_lr=True,
            patience=30,
            close_mosaic=10,
            project=config["project"],
            exist_ok=True,
            hsv_h=augmentations["hsv_h"],
            hsv_s=augmentations["hsv_s"],
            hsv_v=augmentations["hsv_v"],
            degrees=augmentations["degrees"],
            translate=augmentations["translate"],
            scale=augmentations["scale"],
            shear=augmentations["shear"],
            flipud=augmentations["flipud"],
            fliplr=augmentations["fliplr"],
        )
    finally:
        writer.close()

    print(f"训练完成，结果保存在：{config['project']}/{config['run_name']}")
    print(f"TensorBoard 日志保存在：runs/tf_monitor/{config['run_name']}")


def main() -> None:
    """PyCharm direct-run entrypoint."""

    train_yolo_obb()


if __name__ == "__main__":
    main()
