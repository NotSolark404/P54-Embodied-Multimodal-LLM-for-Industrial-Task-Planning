"""
vision_server.py
----------------
Updated for tray + disc detection.
Runs on RevPi Core SE. Serves scene JSON at /scene.

Install: pip3 install flask opencv-python-headless numpy ultralytics picamera2
Run:     python3 vision_server.py
"""
from flask import Flask, jsonify
import numpy as np
import cv2
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load camera
def load_camera():
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(
            main={"size": (1280, 720), "format": "RGB888"}
        ))
        cam.start()
        logger.info("Camera: Pi Camera Module 3")
        return cam, "picamera"
    except Exception:
        cap = cv2.VideoCapture(0)
        logger.info("Camera: USB webcam fallback")
        return cap, "webcam"

camera, cam_type = load_camera()

# Load disc detector
from camera_backend.disc_detector import DiscDetector
detector = DiscDetector(
    min_disc_radius=15,
    max_disc_radius=80,
    tray_min_area=5000,
)


@app.route("/scene")
def get_scene():
    # Capture frame
    if cam_type == "picamera":
        frame = camera.capture_array()          # RGB
    else:
        ret, bgr = camera.read()
        frame    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)

    # Run detection
    scene = detector.detect(frame)

    logger.info(
        f"[Scene] {len(scene['objects'])} objects, "
        f"{len(scene['trays'])} trays"
    )
    return jsonify(scene)


@app.route("/frame")
def get_frame():
    """Return annotated frame as JPEG for debugging."""
    if cam_type == "picamera":
        frame = camera.capture_array()
        bgr   = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    else:
        _, bgr = camera.read()

    _, buf = cv2.imencode(".jpg", bgr)
    return buf.tobytes(), 200, {"Content-Type": "image/jpeg"}


@app.route("/health")
def health():
    return jsonify({"status": "ok", "camera": cam_type})


if __name__ == "__main__":
    print("Vision server running on port 5000")
    app.run(host="0.0.0.0", port=5000, debug=False)