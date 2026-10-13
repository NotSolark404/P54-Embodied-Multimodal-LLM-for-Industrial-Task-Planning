"""Software-only validation tests. No images, label files or models are generated.

Virtual paths, decoder doubles and in-memory annotation strings are TEST inputs,
not real workspace observations or training evidence.
"""

from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import yaml

from fine_tuning.yolov8_real_workspace import train as training
from fine_tuning.yolov8_real_workspace import validate_dataset as validation


@pytest.mark.parametrize("row", [
    "0 0.5 0.5", "0.5 0.5 0.5 0.2 0.2", "-1 0.5 0.5 0.2 0.2",
    "1 0.5 0.5 0.2 0.2", "0 nan 0.5 0.2 0.2", "0 0.5 0.5 0 0.2",
    "0 1.1 0.5 0.2 0.2", "0 0.05 0.5 0.2 0.2", "0 0.5 0.5 inf 0.2",
])
def test_invalid_annotation_rows(row):
    with pytest.raises(ValueError, match="line 1"):
        validation.parse_labels(row, 1)


def test_annotation_contract():
    assert validation.parse_labels("", 1) == []
    assert validation.parse_labels("0 0.5 0.5 1 1\n", 1) == [0]


@pytest.mark.parametrize("config", [
    {"names": ["TEST_ONLY"]},
    {"classes_confirmed": True, "names": []},
    {"classes_confirmed": True, "names": {1: "TEST_ONLY"}},
    {"classes_confirmed": True, "names": ["TEST_ONLY", "TEST_ONLY"]},
    {"classes_confirmed": True, "names": ["TEST_ONLY"], "nc": 7},
])
def test_unconfirmed_or_invalid_classes(config):
    with pytest.raises(ValueError):
        validation.class_names(config)


def test_shipped_dataset_and_training_are_not_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(training, "RUNS", tmp_path / "runs")
    monkeypatch.setitem(sys.modules, "ultralytics", None)
    report = validation.validate_dataset()
    assert any("annotations require confirmation" in error for error in report.errors)
    with pytest.raises(ValueError, match="annotations require confirmation"):
        training.train()
    assert not training.RUNS.exists()


@pytest.fixture
def virtual_dataset(monkeypatch, tmp_path):
    """Fully mocked filesystem and decoder: creates no image or label files."""
    root = tmp_path / "virtual"
    config = {"path": ".", "classes_confirmed": True, "names": ["TEST_ONLY_CLASS"]}
    config.update({s: f"images/{s}" for s in validation.SPLITS})
    contents = {root / "data.yaml": yaml.safe_dump(config)}
    listings = {}
    for split in validation.SPLITS:
        image = root / "images" / split / "TEST_ONLY.jpg"
        label = root / "labels" / split / "TEST_ONLY.txt"
        listings[image.parent] = [image]
        listings[label.parent] = [label]
        contents[label] = "0 0.5 0.5 0.2 0.2"

    def read_text(path, **kwargs):
        if path not in contents:
            raise FileNotFoundError(str(path))
        return contents[path]

    monkeypatch.setattr(Path, "read_text", read_text)
    monkeypatch.setattr(Path, "rglob", lambda path, pattern: iter(listings.get(path, [])))
    monkeypatch.setattr(Path, "is_dir", lambda path: path in listings)
    monkeypatch.setattr(Path, "is_file", lambda path: True)
    # A decoder double with deterministic distinct byte signatures; no raster data.
    monkeypatch.setattr(validation.cv2, "imread", lambda path, flags: SimpleNamespace(
        size=3, shape=(1, 1, 3), tobytes=lambda: path.encode()))
    return root, contents, listings


def test_virtual_dataset_success(virtual_dataset):
    root, _, _ = virtual_dataset
    report = validation.validate_dataset(root / "data.yaml", require_test=True)
    report.require_valid()
    assert report.images == {"train": 1, "val": 1, "test": 1}
    assert report.instances["train"] == {0: 1}


def test_missing_label_and_orphan(virtual_dataset):
    root, contents, listings = virtual_dataset
    del contents[root / "labels/train/TEST_ONLY.txt"]
    listings[root / "labels/val"].append(root / "labels/val/orphan.txt")
    report = validation.validate_dataset(root / "data.yaml")
    assert any("labels/train/TEST_ONLY.txt" in e for e in report.errors)
    assert any("Orphan" in e for e in report.errors)


def test_corrupt_image(virtual_dataset, monkeypatch):
    root, _, _ = virtual_dataset
    monkeypatch.setattr(validation.cv2, "imread", lambda *args: None)
    assert any("corrupt" in e for e in validation.validate_dataset(root / "data.yaml").errors)


def test_duplicate_image_leakage(virtual_dataset, monkeypatch):
    root, _, _ = virtual_dataset
    monkeypatch.setattr(validation.cv2, "imread", lambda *args: SimpleNamespace(
        size=3, shape=(1, 1, 3), tobytes=lambda: b"TEST_DECODER_SIGNATURE"))
    assert any("split leakage" in e for e in validation.validate_dataset(root / "data.yaml").errors)


def test_empty_splits(virtual_dataset):
    root, _, listings = virtual_dataset
    listings[root / "images/test"] = []
    listings[root / "labels/test"] = []
    validation.validate_dataset(root / "data.yaml").require_valid()
    assert any("test: no images" in e for e in validation.validate_dataset(root / "data.yaml", True).errors)
    listings[root / "images/train"] = []
    assert any("train: no images" in e for e in validation.validate_dataset(root / "data.yaml").errors)


def test_training_dispatch_and_no_overwrite(monkeypatch, tmp_path):
    report = validation.ValidationReport(tmp_path, names=["TEST_ONLY_CLASS"], images={"test": 0})
    monkeypatch.setattr(training, "validate_dataset", lambda data: report)
    monkeypatch.setattr(training, "RUNS", tmp_path / "runs")
    calls = []
    # No actual model load or training occurs.
    model = SimpleNamespace(train=lambda **kwargs: calls.append(kwargs))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=lambda *a, **kw: model))
    training.train(name="TEST_ONLY")
    assert calls[0]["resume"] is False
    assert calls[0]["project"] == str(tmp_path / "runs")
    manifest = yaml.safe_load(Path(calls[0]["data"]).read_text())
    assert manifest["path"] == str(tmp_path)
    assert manifest["names"] == ["TEST_ONLY_CLASS"]
    assert "classes_confirmed" not in manifest
    with pytest.raises(ValueError, match="already exists"):
        training.train(name="TEST_ONLY")
    with pytest.raises(ValueError, match="Run name"):
        training.train(name="../synthetic")
    assert len(calls) == 1
