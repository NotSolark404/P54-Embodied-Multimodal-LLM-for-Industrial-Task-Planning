"""
webcam_camera.py
----------------
USB webcam fallback camera driver.
"""
import cv2
import numpy as np
import logging
from camera_backend.camera_interface import CameraFrame

logger = logging.getLogger(__name__)


class WebcamCamera:
    def __init__(self, device: int = 0):
        self.cap = cv2.VideoCapture(device)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open webcam device {device}")
        logger.info(f"[Webcam] Opened device {device}")

    def get_frame(self) -> CameraFrame:
        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError("Failed to capture frame from webcam")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return CameraFrame(rgb=rgb)

    def stop(self):
        self.cap.release()