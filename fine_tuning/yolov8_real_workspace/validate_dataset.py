"""Validate the real-workspace YOLO detection dataset without loading a model."""

import argparse
from collections import Counter
from dataclasses import dataclass, field
import hashlib
import math
from pathlib import Path

import cv2
import yaml

DEFAULT_DATA = Path(__file__).resolve().parent / "dataset" / "data.yaml"
SPLITS = ("train", "val", "test")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def class_names(config: dict) -> list[str]:
    if config.get("classes_confirmed") is not True:
        raise ValueError("Physical class list requires confirmation: set classes_confirmed only after lab review")
    names = config.get("names")
    if isinstance(names, dict):
        if any(type(key) is not int for key in names) or set(names) != set(range(len(names))):
            raise ValueError("Class IDs must be contiguous integers starting at zero")
        names = [names[i] for i in range(len(names))]
    if (not isinstance(names, list) or not names
            or any(not isinstance(name, str) or not name.strip() for name in names)):
        raise ValueError("names must contain confirmed nonempty class names")
    names = [name.strip() for name in names]
    if len(set(names)) != len(names):
        raise ValueError("Class names must be unique")
    if "nc" in config and (type(config["nc"]) is not int or config["nc"] != len(names)):
        raise ValueError("nc does not match names")
    return names


def parse_labels(text: str, num_classes: int) -> list[int]:
    """Validate YOLO rows; an explicit empty file means reviewed background."""
    classes = []
    for line_num, line in enumerate(text.splitlines(), 1):
        fields = line.split()
        if not fields:
            continue
        try:
            if len(fields) != 5:
                raise ValueError("expected class_id x_center y_center width height")
            if not fields[0].isascii() or not fields[0].isdigit():
                raise ValueError("class ID must be a nonnegative integer")
            class_id = int(fields[0])
            if not 0 <= class_id < num_classes:
                raise ValueError("class ID is outside confirmed names")
            x, y, width, height = map(float, fields[1:])
            if not all(math.isfinite(v) for v in (x, y, width, height)):
                raise ValueError("coordinates must be finite")
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < width <= 1 and 0 < height <= 1):
                raise ValueError("coordinates must be normalized; box sizes must be positive")
            if min(x - width / 2, y - height / 2) < -1e-6 or max(x + width / 2, y + height / 2) > 1 + 1e-6:
                raise ValueError("box extends beyond the image")
            classes.append(class_id)
        except ValueError as exc:
            raise ValueError(f"line {line_num}: {exc}") from exc
    return classes


@dataclass
class ValidationReport:
    root: Path
    names: list[str] = field(default_factory=list)
    images: dict[str, int] = field(default_factory=dict)
    instances: dict[str, dict[int, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def require_valid(self) -> None:
        if self.errors:
            raise ValueError("Dataset is not ready:\n" + "\n".join(self.errors))


def validate_dataset(data: str | Path = DEFAULT_DATA, require_test: bool = False) -> ValidationReport:
    data = Path(data).resolve()
    report = ValidationReport(root=data.parent)
    try:
        config = yaml.safe_load(data.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Dataset YAML must contain a mapping")
        report.names = class_names(config)
        # A deliberately small layout contract, not arbitrary Ultralytics paths/URLs.
        if config.get("path") != "." or any(config.get(s) != f"images/{s}" for s in SPLITS):
            raise ValueError("Use path: . and images/train, images/val, images/test relative to data.yaml")
    except (OSError, ValueError, yaml.YAMLError) as exc:
        report.errors.append(str(exc))
        return report

    seen_images = {}
    for split in SPLITS:
        image_dir = report.root / "images" / split
        label_dir = report.root / "labels" / split
        counts = Counter()
        images = []
        for directory in (image_dir, label_dir):
            if not directory.is_dir():
                report.errors.append(f"Missing directory: {directory}")
        for path in sorted(image_dir.rglob("*")):
            if path.is_file() and not path.name.startswith("."):
                if path.suffix.lower() not in IMAGE_EXTENSIONS:
                    report.errors.append(f"Unsupported image file: {path}")
                else:
                    images.append(path)
        report.images[split] = len(images)
        if not images and (split != "test" or require_test):
            report.errors.append(f"{split}: no images available")
        expected_labels = set()
        for path in images:
            relative = path.relative_to(image_dir)
            label = label_dir / relative.with_suffix(".txt")
            if label in expected_labels:
                report.errors.append(f"Ambiguous image stem for label: {label}")
            expected_labels.add(label)
            try:
                image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                if image is None or image.size == 0:
                    raise ValueError("unreadable/corrupt image")
                digest = hashlib.sha256(str(image.shape).encode() + image.tobytes()).hexdigest()
                if digest in seen_images:
                    report.errors.append(f"Duplicate image (possible split leakage): {path} and {seen_images[digest]}")
                seen_images[digest] = path
            except (OSError, ValueError, cv2.error) as exc:
                report.errors.append(f"{path}: {exc}")
            try:
                counts.update(parse_labels(label.read_text(encoding="utf-8"), len(report.names)))
            except (OSError, ValueError) as exc:
                report.errors.append(f"{label}: {exc}")
        for label in label_dir.rglob("*"):
            if label.is_file() and not label.name.startswith("."):
                if label not in expected_labels:
                    report.errors.append(f"Orphan or unsupported label file: {label}")
        report.instances[split] = dict(counts)
        if split == "train":
            for class_id, name in enumerate(report.names):
                if not counts[class_id]:
                    report.errors.append(f"train: no labelled instances of class {class_id} ({name})")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--require-test", action="store_true")
    args = parser.parse_args(argv)
    report = validate_dataset(args.data, args.require_test)
    print(f"Images per split: {report.images}")
    print(f"Labelled instances per split/class ID: {report.instances}")
    for error in report.errors:
        print(f"ERROR: {error}")
    print("NOT READY" if report.errors else "Dataset structure valid; annotation quality still requires human review.")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
