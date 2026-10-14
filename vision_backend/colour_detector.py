"""
colour_detector.py
------------------
Detects the grey tray and the two white trays in a ZED camera frame.
Uses HSV colour thresholding — no model training required.

Returns a list of dicts: {"label": str, "bounding_box": [x, y, w, h]}
"""

import cv2
import numpy as np

MIN_AREA = 1000  # minimum contour area to filter out noise

COLOUR_RANGES = {
    "grey tray": [
        (np.array([0, 0, 50]),  np.array([180, 50, 200])),  # low saturation = grey
    ],
    "left tray": [
        (np.array([0, 0, 200]), np.array([180, 30, 255])),  # high brightness, low sat = white
    ],
    "right tray": [
        (np.array([0, 0, 200]), np.array([180, 30, 255])),  # same colour, split by position
    ],
}


def _get_mask(hsv, ranges):
    mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
    for lower, upper in ranges:
        mask |= cv2.inRange(hsv, lower, upper)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _largest_box(mask):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) > MIN_AREA]
    if not contours:
        return None
    x, y, w, h = cv2.boundingRect(max(contours, key=cv2.contourArea))
    return [x, y, w, h]


def _split_white_trays(mask, frame_width):
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) > MIN_AREA]
    left, right = [], []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if (x + w // 2) < frame_width // 2:
            left.append([x, y, w, h])
        else:
            right.append([x, y, w, h])
    result = {}
    if left:
        result["left tray"] = left[0]
    if right:
        result["right tray"] = right[0]
    return result


def detect(frame_rgb: np.ndarray) -> list[dict]:
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    h, w = frame_rgb.shape[:2]
    detections = []

    # Grey tray
    grey_mask = _get_mask(hsv, COLOUR_RANGES["grey tray"])
    box = _largest_box(grey_mask)
    if box:
        detections.append({"label": "grey tray", "bounding_box": box})

    # White trays — split by x position
    white_mask = _get_mask(hsv, COLOUR_RANGES["left tray"])
    for label, box in _split_white_trays(white_mask, w).items():
        detections.append({"label": label, "bounding_box": box})

    return detections


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from camera_backend.zed_rstp import capture_frame

    frame = capture_frame()
    results = detect(frame)
    print(f"Detected {len(results)} objects:")
    for r in results:
        print(f"  {r['label']}: {r['bounding_box']}")

    vis = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
    for r in results:
        x, y, w, h = r["bounding_box"]
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.putText(vis, r["label"], (x, y - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
    cv2.imwrite("detection_test.jpg", vis)
    print("Saved detection_test.jpg")