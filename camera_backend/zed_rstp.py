# camera_backend/zed_rtsp.py
import os
import cv2
import numpy as np

RTSP_URL = os.getenv("CAMERA_RTSP_URL", "rtsp://172.21.0.94:8554/zed")

# Must be set before cv2 opens the stream
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


def capture_frame() -> np.ndarray:
    """
    Grab a single frame from the ZED RTSP stream.
    ZED stereo streams are side-by-side (left|right) — we crop left half only.
    Returns an RGB numpy array.
    """
    cap = cv2.VideoCapture(RTSP_URL, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open RTSP stream: {RTSP_URL}")

    # Drain a few frames so we don't get a stale buffer frame
    for _ in range(5):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Failed to read frame from ZED stream")

    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


if __name__ == "__main__":
    frame = capture_frame()
    print(f"Frame shape: {frame.shape}")
    cv2.imwrite("test_frame.jpg", cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
    print("Saved test_frame.jpg")