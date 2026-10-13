# camera_backend/zed_rtsp.py
import os
from pathlib import Path

import cv2
import numpy as np

RTSP_URL = os.getenv("CAMERA_RTSP_URL", "rtsp://172.21.0.94:8554/zed")

# Must be set before cv2 opens the stream
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

# Cam/test_frame.jpg was visually confirmed to contain two 672x376 views.
# Dimensions alone cannot prove stereo layout. Reconfirm the layout if the
# stream configuration changes, before updating this expected (height, width).
CONFIRMED_STEREO_SHAPE = (376, 1344)
LEFT_FRAME_PATH = Path(__file__).resolve().parent / "test_frame_left.jpg"


def left_frame_rgb(frame: np.ndarray) -> np.ndarray:
    """Extract RGB from the confirmed side-by-side BGR stream; no depth."""
    if frame is None:
        raise RuntimeError("Missing frame from ZED stream")
    if (
        not isinstance(frame, np.ndarray)
        or frame.ndim != 3
        or frame.shape[2] != 3
        or frame.size == 0
        or frame.dtype != np.uint8
    ):
        raise RuntimeError("Invalid ZED frame: expected a non-empty uint8 BGR image with 3 channels")
    if frame.shape[:2] != CONFIRMED_STEREO_SHAPE:
        raise RuntimeError(
            f"Unconfirmed ZED frame layout: got {frame.shape[:2]} (height, width), "
            f"expected {CONFIRMED_STEREO_SHAPE}. Verify side-by-side layout before cropping."
        )
    left_bgr = frame[:, : frame.shape[1] // 2]
    return cv2.cvtColor(left_bgr, cv2.COLOR_BGR2RGB)


def capture_frame() -> np.ndarray:
    """Grab the left view from the confirmed ZED RTSP stream as RGB."""
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    try:
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open RTSP stream: {RTSP_URL}")

        # Drain a few frames so we don't get a stale buffer frame
        for _ in range(5):
            cap.read()

        ret, frame = cap.read()
        if not ret:
            raise RuntimeError("Failed to read frame from ZED stream")
        return left_frame_rgb(frame)
    finally:
        cap.release()


def save_left_frame(frame_rgb: np.ndarray) -> None:
    """Save the returned RGB view using OpenCV's BGR encoding convention."""
    if not cv2.imwrite(str(LEFT_FRAME_PATH), cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)):
        raise RuntimeError(f"Failed to save left camera image: {LEFT_FRAME_PATH}")


if __name__ == "__main__":
    frame = capture_frame()
    print(f"Left RGB frame shape: {frame.shape}")
    save_left_frame(frame)
    print(f"Saved {LEFT_FRAME_PATH}")
