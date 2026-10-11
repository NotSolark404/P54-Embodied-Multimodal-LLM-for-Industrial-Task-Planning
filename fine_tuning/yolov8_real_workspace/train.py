"""Train YOLOv8 on reviewed real images; refuses an unprepared dataset."""

import argparse
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fine_tuning.yolov8_real_workspace.validate_dataset import DEFAULT_DATA, validate_dataset

RUNS = Path(__file__).resolve().parent / "runs"
BASE_WEIGHTS = ROOT / "simulation_backend" / "vision" / "detection_weight" / "yolov8n.pt"


def train(data=DEFAULT_DATA, weights=BASE_WEIGHTS, name="real_workspace", epochs=50,
          imgsz=640, batch=8, device="cpu", seed=54):
    report = validate_dataset(data)
    report.require_valid()  # Before importing Ultralytics, loading weights or creating outputs.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
        raise ValueError("Run name must contain only letters, digits, underscores or hyphens")
    if any(type(v) is not int or v <= 0 for v in (epochs, imgsz, batch)):
        raise ValueError("epochs, imgsz and batch must be positive integers")
    weights = Path(weights).resolve()
    if not weights.is_file() or weights.suffix != ".pt":
        raise ValueError("Provide an existing local YOLOv8 .pt checkpoint; no automatic download")
    run_dir = RUNS / name
    if run_dir.exists():
        raise ValueError(f"Run already exists; choose a new --name: {run_dir}")
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Training requires ultralytics and its PyTorch dependencies") from exc
    model = YOLO(str(weights), task="detect")
    run_dir.mkdir(parents=True, exist_ok=False)
    resolved_data = {
        "path": str(report.root), "train": "images/train", "val": "images/val",
        "names": report.names, "nc": len(report.names),
    }
    if report.images["test"]:
        resolved_data["test"] = "images/test"
    manifest = run_dir / "data.resolved.yaml"
    manifest.write_text(yaml.safe_dump(resolved_data, sort_keys=False), encoding="utf-8")
    # exist_ok applies only to the freshly reserved run directory above.
    return model.train(data=str(manifest), epochs=epochs, imgsz=imgsz, batch=batch,
                       device=device, seed=seed, workers=0, project=str(RUNS), name=name,
                       exist_ok=True, resume=False, cache=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--weights", type=Path, default=BASE_WEIGHTS)
    parser.add_argument("--name", default="real_workspace")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=54)
    args = parser.parse_args(argv)
    try:
        train(**vars(args))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Training not completed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
