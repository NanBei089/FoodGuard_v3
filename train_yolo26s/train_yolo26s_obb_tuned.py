from __future__ import annotations

from pathlib import Path
from typing import Any


# PyCharm 运行说明：
# 1. 解释器选择 conda 环境 `train_env`
# 2. 工作目录保持为当前项目根目录
# 3. 右键运行本文件即可开始训练 yolo26s-obb 基线模型
PYCHARM_CONDA_ENV = "train_env"


def build_default_config() -> dict[str, Any]:
    """返回与根目录 train.py 风格一致的默认训练配置。"""

    return {
        "model_name": "yolo26s-obb.pt",
        "task": "obb",
        "data_yaml": "./dataset/dataset.yaml",
        "batch_size": -1,
        "epochs": 180,
        "img_size": 896,
        "device": 0,
        "workers": 4,
        "run_name": "yolo26s-obb-baseline-tuned",
        "project": "runs/train",
    }


def _resolve_data_yaml(data_yaml: str) -> str:
    """优先使用传入的 data.yaml，不存在时回退到默认数据集配置。"""

    preferred = Path(data_yaml)
    if preferred.exists():
        return str(preferred)

    fallback = Path("./dataset/dataset.yaml")
    if fallback.exists():
        print(f"未找到 {preferred}，自动使用 {fallback}")
        return str(fallback)

    raise FileNotFoundError(f"数据集配置文件不存在：{preferred}，且未找到 {fallback}")


def _resolve_device(device: int | str) -> int | str:
    """优先使用 GPU，CUDA 不可用时自动切换到 CPU。"""

    if isinstance(device, str) and device.lower() == "cpu":
        return "cpu"

    try:
        import torch
    except ModuleNotFoundError as exc:
        raise RuntimeError("未检测到 PyTorch，请先在 conda 的 train_env 环境中安装依赖。") from exc

    if str(device) == "0" and not torch.cuda.is_available():
        print("检测到 CUDA 不可用，自动切换到 CPU")
        return "cpu"
    return device


def load_yolo_model(model_name: str, yolo_cls=None):
    """加载 OBB 模型，确保任务类型固定为 obb。"""

    if yolo_cls is None:
        try:
            from ultralytics import YOLO
        except ModuleNotFoundError as exc:
            raise RuntimeError("未检测到 ultralytics，请先激活 train_env 并安装 requirements.txt。") from exc

        yolo_cls = YOLO

    return yolo_cls(model_name, task="obb")


def _create_tf_writer(run_name: str):
    """创建 TensorBoard 日志写入器，用于记录训练过程。"""

    try:
        import tensorflow as tf
    except ModuleNotFoundError as exc:
        raise RuntimeError("未检测到 TensorFlow，如不需要监控日志可移除相关代码。") from exc

    log_dir = Path("runs/tf_monitor") / run_name
    log_dir.mkdir(parents=True, exist_ok=True)

    print(f"TensorFlow 版本: {tf.__version__}")
    print(f"TensorFlow GPU 设备数: {len(tf.config.list_physical_devices('GPU'))}")
    print(f"TensorBoard 日志目录: {log_dir}")
    return tf.summary.create_file_writer(str(log_dir))


def _register_tf_callback(model, writer) -> None:
    """将训练损失和验证指标写入 TensorBoard，方便在 PyCharm 中查看。"""

    import tensorflow as tf

    loss_names = [
        "train/box_loss",
        "train/cls_loss",
        "train/dfl_loss",
        "train/angle_loss",
    ]

    def on_fit_epoch_end(trainer) -> None:
        epoch = int(getattr(trainer, "epoch", 0)) + 1

        with writer.as_default():
            tloss = getattr(trainer, "tloss", None)
            if tloss is not None:
                values = tloss.tolist() if hasattr(tloss, "tolist") else list(tloss)
                for idx, value in enumerate(values[: len(loss_names)]):
                    tf.summary.scalar(loss_names[idx], float(value), step=epoch)

            metrics = getattr(trainer, "metrics", {}) or {}
            for key, value in metrics.items():
                try:
                    scalar = float(value)
                except (TypeError, ValueError):
                    continue
                safe_key = str(key).replace("/", "_").replace("(", "").replace(")", "")
                tf.summary.scalar(f"val/{safe_key}", scalar, step=epoch)

            writer.flush()

    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)


def _register_progress_callback(model, total_epochs: int) -> None:
    """使用 tqdm 显示训练轮次进度，便于在终端或 PyCharm 控制台观察。"""

    from tqdm.auto import tqdm

    epoch_bar = tqdm(total=total_epochs, desc="Training", unit="epoch")

    def on_fit_epoch_end(trainer) -> None:
        current_epoch = int(getattr(trainer, "epoch", 0)) + 1
        tloss = getattr(trainer, "tloss", None)
        loss_text = ""
        if tloss is not None:
            values = tloss.tolist() if hasattr(tloss, "tolist") else list(tloss)
            if values:
                loss_text = f"loss={sum(float(value) for value in values):.4f}"
        epoch_bar.set_postfix_str(f"epoch {current_epoch}/{total_epochs} {loss_text}".strip())
        epoch_bar.update(1)

    def on_train_end(trainer) -> None:
        if epoch_bar.n < epoch_bar.total:
            epoch_bar.update(epoch_bar.total - epoch_bar.n)
        epoch_bar.close()

    model.add_callback("on_fit_epoch_end", on_fit_epoch_end)
    model.add_callback("on_train_end", on_train_end)


def train_yolo_obb(config: dict[str, Any] | None = None) -> None:
    """按根目录 train.py 的使用方式训练 yolo26s-obb 基线模型。"""

    config = build_default_config() if config is None else config
    model = load_yolo_model(config["model_name"])

    # 这里尽量沿用根目录 train.py 的增强参数，保持基线口径一致。
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
    """PyCharm 直接运行入口。"""

    train_yolo_obb()


if __name__ == "__main__":
    main()
