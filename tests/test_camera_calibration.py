"""TEST values only. No fixture contains measured physical calibration."""

import json

import pytest

from physical_backend.vision.calibration import load_calibration


@pytest.fixture
def test_values_only():
    # Arbitrary TEST intrinsics and identity transform for schema checks only.
    return {
        "schema_version": 1,
        "image_width": 640,
        "image_height": 480,
        "camera_matrix": [[500, 0, 320], [0, 500, 240], [0, 0, 1]],
        "distortion_coefficients": [0, 0, 0, 0, 0],
        "target_frame": "workspace",
        "camera_to_target": [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]],
    }


def test_missing_calibration(tmp_path):
    assert load_calibration(None) is None
    assert load_calibration("") is None
    with pytest.raises(FileNotFoundError):
        load_calibration(tmp_path / "missing.json")


def test_valid_test_fixture(tmp_path, test_values_only):
    path = tmp_path / "TEST_ONLY_calibration.json"
    path.write_text(json.dumps(test_values_only))
    calibration = load_calibration(path)
    assert calibration.image_width == 640
    assert calibration.camera_matrix.shape == (3, 3)
    assert calibration.camera_to_target.shape == (4, 4)
    assert calibration.target_frame == "workspace"


@pytest.mark.parametrize("payload", ["not json", "null", "[]", "{}"])
def test_malformed_file(tmp_path, payload):
    path = tmp_path / "invalid.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="Invalid calibration file"):
        load_calibration(path)


@pytest.mark.parametrize("field,value", [
    ("schema_version", 2),
    ("image_width", 0),
    ("image_height", True),
    ("target_frame", "unknown"),
    ("camera_matrix", [[1, 0], [0, 1]]),
    ("camera_matrix", [[0, 0, 0], [0, 1, 0], [0, 0, 1]]),
    ("distortion_coefficients", [0, 0]),
    ("distortion_coefficients", [0, 0, 0, float("nan")]),
    ("camera_to_target", [[1, 0, 0, 0], [0, 2, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
    ("camera_to_target", [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]),
    ("camera_to_target", [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 1, 1]]),
])
def test_invalid_calibration_values(tmp_path, test_values_only, field, value):
    test_values_only[field] = value
    path = tmp_path / "TEST_ONLY_invalid.json"
    path.write_text(json.dumps(test_values_only))
    with pytest.raises(ValueError):
        load_calibration(path)
