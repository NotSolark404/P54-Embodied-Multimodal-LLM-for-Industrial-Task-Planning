"""Load measured calibration JSON. Missing calibration is None, never defaults."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np


@dataclass
class Calibration:
    image_width: int
    image_height: int
    camera_matrix: np.ndarray
    distortion_coefficients: np.ndarray
    target_frame: str  # 'robot' or 'workspace'
    camera_to_target: np.ndarray  # target_point = T @ camera_point; metres
    schema_version: int = 1

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError("Unsupported calibration schema_version")
        if any(type(v) is not int or v <= 0 for v in (self.image_width, self.image_height)):
            raise ValueError("Calibration image dimensions must be positive integers")
        if self.target_frame not in ("robot", "workspace"):
            raise ValueError("target_frame must be robot or workspace")
        self.camera_matrix = np.array(self.camera_matrix, dtype=float)
        self.distortion_coefficients = np.array(self.distortion_coefficients, dtype=float)
        self.camera_to_target = np.array(self.camera_to_target, dtype=float)
        k, d, t = self.camera_matrix, self.distortion_coefficients, self.camera_to_target
        if not all(np.isfinite(a).all() for a in (k, d, t)):
            raise ValueError("Calibration values must be finite")
        if k.shape != (3, 3) or not np.allclose(k[2], [0, 0, 1]) or k[0, 0] <= 0 or k[1, 1] <= 0 or not np.isclose(k[1, 0], 0):
            raise ValueError("camera_matrix must be a valid 3×3 pinhole intrinsic matrix")
        if d.ndim != 1 or d.size not in (4, 5, 8, 12, 14):
            raise ValueError("distortion_coefficients must contain 4, 5, 8, 12 or 14 OpenCV pinhole coefficients")
        if t.shape != (4, 4) or not np.allclose(t[3], [0, 0, 0, 1]):
            raise ValueError("camera_to_target must be a homogeneous 4×4 transform")
        rotation = t[:3, :3]
        if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6) or not np.isclose(np.linalg.det(rotation), 1, atol=1e-6):
            raise ValueError("camera_to_target rotation must be orthonormal with determinant +1")


def load_calibration(path: str | Path | None) -> Calibration | None:
    """None/empty path means uncalibrated. An explicitly missing file is an error."""
    if path is None or path == "":
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Calibration file must contain a JSON object")
        return Calibration(**data)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid calibration file {path}: {exc}") from exc
