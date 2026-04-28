from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

DEFAULT_WEIGHTS = Path("runs/obb/runs/train_tuned/yolo26s-obb-geo-tuned/weights/best.pt")
DEFAULT_IMGSZ = 640
DEFAULT_OPSET = 13
DEFAULT_DYNAMIC = False
DEFAULT_SIMPLIFY = False
DEFAULT_HALF = False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the current YOLO26-OBB model to ONNX.")
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="Path to a trained .pt checkpoint.")
    parser.add_argument("--imgsz", type=int, default=None, help="Export image size. Defaults to args.yaml imgsz when available.")
    parser.add_argument("--output", type=Path, default=None, help="Optional ONNX output path.")
    parser.add_argument("--opset", type=int, default=DEFAULT_OPSET, help="ONNX opset version.")
    parser.add_argument("--device", default=None, help="Export device, for example 0 or cpu. Defaults to auto-detect.")
    parser.add_argument("--dynamic", action="store_true", help="Export with dynamic input shape.")
    parser.add_argument("--simplify", action="store_true", help="Simplify the exported ONNX graph.")
    parser.add_argument("--half", action="store_true", help="Export in FP16. Requires GPU.")
    return parser.parse_args(argv)


def resolve_device() -> str | int:
    import torch

    return 0 if torch.cuda.is_available() else "cpu"


def _find_args_yaml(weights: Path) -> Path | None:
    if weights.parent.name == "weights":
        args_yaml = weights.parent.parent / "args.yaml"
        if args_yaml.exists():
            return args_yaml
    return None


def _read_run_metadata(weights: Path) -> dict[str, str | int]:
    args_yaml = _find_args_yaml(weights)
    if args_yaml is None:
        return {}

    metadata: dict[str, str | int] = {}
    for raw_line in args_yaml.read_text(encoding="utf-8").splitlines():
        if ":" not in raw_line:
            continue

        key, raw_value = raw_line.split(":", 1)
        key = key.strip()
        value = raw_value.strip().strip("'\"")

        if key == "imgsz":
            try:
                metadata["imgsz"] = int(value)
            except ValueError:
                continue
        elif key == "name" and value:
            metadata["name"] = value

    return metadata


def _derive_output_name(weights: Path, metadata: dict[str, str | int]) -> str:
    run_name = metadata.get("name")
    if isinstance(run_name, str) and run_name:
        return run_name

    if weights.parent.name == "weights":
        return weights.parent.parent.name

    return weights.stem


def resolve_export_settings(
    weights: Path,
    imgsz: int | None = None,
    output: Path | None = None,
) -> dict[str, Path | int]:
    metadata = _read_run_metadata(weights)
    resolved_imgsz = imgsz if imgsz is not None else int(metadata.get("imgsz", DEFAULT_IMGSZ))

    resolved_output = output
    if resolved_output is None:
        resolved_output = weights.parent / f"{_derive_output_name(weights, metadata)}.onnx"
    elif resolved_output.suffix.lower() != ".onnx":
        resolved_output = resolved_output.with_suffix(".onnx")

    return {
        "weights": weights,
        "imgsz": resolved_imgsz,
        "output": resolved_output,
    }


def load_yolo_model(
    weights: Path,
    yolo_cls=None,
    register_modules: Callable[[], None] | None = None,
):
    if register_modules is None:
        try:
            from ultralytics_ext.register import register_custom_modules
        except ModuleNotFoundError:
            register_modules = lambda: None
        else:
            register_modules = register_custom_modules

    register_modules()

    if yolo_cls is None:
        from ultralytics import YOLO

        yolo_cls = YOLO

    return yolo_cls(str(weights), task="obb")


def export_model(
    weights: Path,
    model=None,
    imgsz: int | None = None,
    output: Path | None = None,
    opset: int = DEFAULT_OPSET,
    device: str | int | None = None,
    dynamic: bool = DEFAULT_DYNAMIC,
    simplify: bool = DEFAULT_SIMPLIFY,
    half: bool = DEFAULT_HALF,
) -> Path:
    if not weights.exists():
        raise FileNotFoundError(f"Weights not found: {weights}. Please run training first.")

    settings = resolve_export_settings(weights, imgsz=imgsz, output=output)

    resolved_device = device
    if model is None:
        resolved_device = resolve_device() if device is None else device
        if half and str(resolved_device).lower() == "cpu":
            raise ValueError("HALF=True requires GPU. Set --device 0 or disable --half.")
        model = load_yolo_model(weights)

    export_kwargs: dict[str, Any] = {
        "format": "onnx",
        "imgsz": settings["imgsz"],
        "opset": opset,
        "dynamic": dynamic,
        "simplify": simplify,
        "half": half,
    }
    if resolved_device is not None:
        export_kwargs["device"] = resolved_device

    exported_path = Path(model.export(**export_kwargs))
    final_output = Path(settings["output"])
    final_output.parent.mkdir(parents=True, exist_ok=True)

    if exported_path.resolve() != final_output.resolve():
        if final_output.exists():
            final_output.unlink()
        exported_path.replace(final_output)

    return final_output


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    final_output = export_model(
        weights=args.weights,
        imgsz=args.imgsz,
        output=args.output,
        opset=args.opset,
        device=args.device,
        dynamic=args.dynamic,
        simplify=args.simplify,
        half=args.half,
    )
    print(f"Exported ONNX model to: {final_output}")


if __name__ == "__main__":
    main()
