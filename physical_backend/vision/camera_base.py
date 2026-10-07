"""RGB camera contract. No simulated depth, segmentation, or world positions."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import math
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class CameraCapabilities:
    depth: bool = False
    segmentation: bool = False


@dataclass
class PhysicalFrame:
    image: np.ndarray
    color_order: Literal["RGB", "BGR"]
    timestamp: float  # Host Unix time in seconds after capture; not sensor exposure time.
    width: int = field(init=False)
    height: int = field(init=False)

    def __post_init__(self) -> None:
        if (not isinstance(self.image, np.ndarray)
                or self.image.dtype != np.uint8
                or self.image.ndim != 3 or self.image.shape[2] != 3
                or min(self.image.shape[:2]) <= 0):
            raise ValueError("image must be a nonempty H×W×3 uint8 array")
        if self.color_order not in ("RGB", "BGR"):
            raise ValueError("color_order must be RGB or BGR")
        if isinstance(self.timestamp, bool) or not isinstance(self.timestamp, (int, float)) or not math.isfinite(self.timestamp) or self.timestamp < 0:
            raise ValueError("timestamp must be finite, nonnegative Unix seconds")
        self.height, self.width = self.image.shape[:2]

    @property
    def bgr(self) -> np.ndarray:
        return self.image if self.color_order == "BGR" else self.image[:, :, ::-1].copy()

    @property
    def rgb(self) -> np.ndarray:
        return self.image if self.color_order == "RGB" else self.image[:, :, ::-1].copy()


class CameraBase(ABC):
    capabilities = CameraCapabilities()

    @abstractmethod
    def start(self) -> None:
        """Open and start the device."""

    @abstractmethod
    def capture(self) -> PhysicalFrame:
        """Capture a frame; requires start()."""

    @abstractmethod
    def close(self) -> None:
        """Release resources; safe to call repeatedly."""

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
