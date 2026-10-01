"""
disc_detector.py
----------------
Detects coloured discs inside tray slots from camera footage.
Uses OpenCV for shape detection (HoughCircles) and colour segmentation.
Returns disc label, colour, shape, slot position, and confidence.

Works without a trained YOLO model — pure computer vision.
"""
import cv2
import numpy as np
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# ── Colour ranges in HSV space ─────────────────────────────────────────────────
# Tune these in the lab by running colour_calibrate() below
COLOUR_RANGES = {
    "red": [
        (np.array([0,   120,  70]),  np.array([10,  255, 255])),
        (np.array([170, 120,  70]),  np.array([180, 255, 255])),  # red wraps in HSV
    ],
    "blue":   [(np.array([100, 100,  50]), np.array([130, 255, 255]))],
    "green":  [(np.array([40,  60,   40]), np.array([80,  255, 255]))],
    "yellow": [(np.array([20,  100,  80]), np.array([35,  255, 255]))],
    "white":  [(np.array([0,   0,   200]), np.array([180, 30,  255]))],
    "black":  [(np.array([0,   0,     0]), np.array([180, 255,  50]))],
}


@dataclass
class DetectedDisc:
    colour:     str            # "red", "blue", "green", "yellow"
    shape:      str            # "circle" (disc), "square", "triangle"
    center_px:  tuple          # (x, y) in pixels
    radius_px:  float          # radius in pixels
    slot_index: Optional[int]  # which slot in the tray (0-indexed), None if not in a slot
    confidence: float          # 0.0 to 1.0
    bbox:       tuple          # (x1, y1, x2, y2)


@dataclass
class DetectedTray:
    center_px:   tuple          # (x, y) in pixels
    bbox:        tuple          # (x1, y1, x2, y2)
    slot_count:  int            # number of slots detected
    slots:       list[tuple]    # list of (x, y) slot center positions in pixels
    discs:       list[DetectedDisc]  # discs found inside this tray


class DiscDetector:
    """
    Detects trays, their slots, and coloured discs inside the slots.
    No YOLO model needed — uses contour detection + colour segmentation.
    """

    def __init__(self,
                 min_disc_radius: int = 15,
                 max_disc_radius: int = 80,
                 tray_min_area: int = 5000):
        self.min_disc_radius = min_disc_radius
        self.max_disc_radius = max_disc_radius
        self.tray_min_area   = tray_min_area
        logger.info("[DiscDetector] Initialised")

    def detect(self, frame: np.ndarray) -> dict:
        """
        Main detection function.
        Returns a scene dict compatible with get_current_scene() format.

        Args:
            frame: RGB image as numpy array (H, W, 3)

        Returns:
            {
              "objects": [
                {
                  "label": "red disc",
                  "colour": "red",
                  "shape": "circle",
                  "position": [cx_px, cy_px],
                  "slot": 0,
                  "tray": "tray_0",
                  "confidence": 0.92
                },
                ...
              ],
              "trays": [
                {
                  "label": "tray_0",
                  "position": [cx_px, cy_px],
                  "slot_count": 4,
                  "slots": [[x0,y0], [x1,y1], ...]
                }
              ]
            }
        """
        bgr    = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        trays  = self._detect_trays(bgr)
        discs  = self._detect_discs(bgr)
        self._assign_discs_to_trays(trays, discs)
        return self._build_scene(trays, discs)

    # ── Tray detection ─────────────────────────────────────────────────────────

    def _detect_trays(self, bgr: np.ndarray) -> list[DetectedTray]:
        """
        Detect rectangular trays using contour detection.
        Trays are assumed to be the largest rectangular objects in the scene.
        """
        gray     = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        blurred  = cv2.GaussianBlur(gray, (7, 7), 0)
        edges    = cv2.Canny(blurred, 30, 100)
        kernel   = np.ones((3, 3), np.uint8)
        dilated  = cv2.dilate(edges, kernel, iterations=2)

        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        trays = []
        for i, cnt in enumerate(contours):
            area = cv2.contourArea(cnt)
            if area < self.tray_min_area:
                continue

            peri   = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)

            # Trays are rectangular — 4 sides
            if len(approx) < 4 or len(approx) > 6:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            cx = x + w // 2
            cy = y + h // 2

            # Detect slots inside the tray
            slots = self._detect_slots(bgr, (x, y, w, h))

            trays.append(DetectedTray(
                center_px  = (cx, cy),
                bbox       = (x, y, x+w, y+h),
                slot_count = len(slots),
                slots      = slots,
                discs      = [],
            ))

        logger.info(f"[DiscDetector] Found {len(trays)} tray(s)")
        return trays

    def _detect_slots(self, bgr: np.ndarray, tray_bbox: tuple) -> list[tuple]:
        """
        Detect circular slots inside a tray region.
        Slots are typically darker circular holes in the tray surface.
        """
        x, y, w, h = tray_bbox
        roi  = bgr[y:y+h, x:x+w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)

        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=30,
            param1=50,
            param2=25,
            minRadius=self.min_disc_radius,
            maxRadius=self.max_disc_radius,
        )

        slots = []
        if circles is not None:
            circles = np.round(circles[0, :]).astype(int)
            for (cx, cy, r) in circles:
                # Convert back to full image coordinates
                slots.append((x + cx, y + cy))

        return slots

    # ── Disc detection ─────────────────────────────────────────────────────────

    def _detect_discs(self, bgr: np.ndarray) -> list[DetectedDisc]:
        """
        Detect all coloured discs in the image using colour segmentation + shape analysis.
        """
        hsv   = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        discs = []

        for colour, ranges in COLOUR_RANGES.items():
            # Build combined mask for this colour
            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
            for (lower, upper) in ranges:
                mask |= cv2.inRange(hsv, lower, upper)

            # Clean up mask
            kernel = np.ones((5, 5), np.uint8)
            mask   = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)
            mask   = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < 500:
                    continue

                # Determine shape
                shape, confidence = self._classify_shape(cnt)

                # Get bounding circle
                (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                cx, cy, radius   = int(cx), int(cy), float(radius)

                if radius < self.min_disc_radius or radius > self.max_disc_radius:
                    continue

                x, y, w, h = cv2.boundingRect(cnt)

                # Circularity check — discs should be ~circular
                circularity = (4 * np.pi * area) / (cv2.arcLength(cnt, True) ** 2 + 1e-5)
                if shape == "circle" and circularity < 0.6:
                    continue

                discs.append(DetectedDisc(
                    colour     = colour,
                    shape      = shape,
                    center_px  = (cx, cy),
                    radius_px  = radius,
                    slot_index = None,
                    confidence = round(min(circularity, 1.0) * confidence, 2),
                    bbox       = (x, y, x+w, y+h),
                ))

        logger.info(f"[DiscDetector] Found {len(discs)} disc(s)")
        return discs

    def _classify_shape(self, contour) -> tuple[str, float]:
        """
        Classify shape as circle, square, or triangle.
        Returns (shape_name, confidence).
        """
        peri   = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.04 * peri, True)
        sides  = len(approx)

        area   = cv2.contourArea(contour)
        circle_area = np.pi * (peri / (2 * np.pi)) ** 2
        circularity = area / (circle_area + 1e-5)

        if circularity > 0.80:
            return "circle", circularity
        elif sides == 3:
            return "triangle", 0.85
        elif sides == 4:
            return "square", 0.85
        elif sides >= 8:
            return "circle", 0.75
        else:
            return "circle", 0.60

    # ── Assignment ─────────────────────────────────────────────────────────────

    def _assign_discs_to_trays(self,
                                trays: list[DetectedTray],
                                discs: list[DetectedDisc]) -> None:
        """
        Assign each disc to the nearest tray slot.
        Modifies discs in-place, setting slot_index.
        """
        for disc in discs:
            dx, dy = disc.center_px
            best_tray  = None
            best_slot  = None
            best_dist  = float("inf")
            best_slot_idx = None

            for tray in trays:
                tx1, ty1, tx2, ty2 = tray.bbox
                # Check if disc center is inside tray bounding box
                if not (tx1 <= dx <= tx2 and ty1 <= dy <= ty2):
                    continue

                for slot_idx, (sx, sy) in enumerate(tray.slots):
                    dist = np.sqrt((dx - sx)**2 + (dy - sy)**2)
                    if dist < best_dist:
                        best_dist     = dist
                        best_tray     = tray
                        best_slot_idx = slot_idx

            if best_tray is not None and best_dist < disc.radius_px * 2:
                disc.slot_index = best_slot_idx
                best_tray.discs.append(disc)

    # ── Scene builder ──────────────────────────────────────────────────────────

    def _build_scene(self,
                     trays: list[DetectedTray],
                     discs: list[DetectedDisc]) -> dict:
        """
        Build scene dict compatible with the P54 pipeline format.
        """
        objects = []
        tray_list = []

        for tray_idx, tray in enumerate(trays):
            tray_label = f"tray_{tray_idx}"
            cx, cy     = tray.center_px

            tray_list.append({
                "label":      tray_label,
                "position":   [cx, cy],
                "slot_count": tray.slot_count,
                "slots":      [[sx, sy] for sx, sy in tray.slots],
            })

            for disc in tray.discs:
                objects.append({
                    "label":      f"{disc.colour} disc",
                    "colour":     disc.colour,
                    "shape":      disc.shape,
                    "position":   list(disc.center_px),
                    "slot":       disc.slot_index,
                    "tray":       tray_label,
                    "confidence": disc.confidence,
                })

        # Discs not in any tray
        for disc in discs:
            if disc.slot_index is None:
                objects.append({
                    "label":      f"{disc.colour} disc",
                    "colour":     disc.colour,
                    "shape":      disc.shape,
                    "position":   list(disc.center_px),
                    "slot":       None,
                    "tray":       None,
                    "confidence": disc.confidence,
                })

        return {"objects": objects, "trays": tray_list}


# ── Colour calibration helper ──────────────────────────────────────────────────

def colour_calibrate(image_path: str):
    """
    Run this in the lab to find the right HSV ranges for your specific discs.
    Click on a disc in the image and it prints the HSV value at that pixel.

    Usage:
        python -c "from camera_backend.disc_detector import colour_calibrate; colour_calibrate('frame.jpg')"
    """
    import cv2

    img = cv2.imread(image_path)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            h, s, v = hsv[y, x]
            print(f"Clicked ({x},{y}) → HSV: H={h}, S={s}, V={v}")
            print(f"  Suggested range: lower=({max(0,h-15)}, {max(0,s-40)}, {max(0,v-40)}), "
                  f"upper=({min(180,h+15)}, 255, 255)")

    cv2.imshow("Colour Calibration — click on discs", img)
    cv2.setMouseCallback("Colour Calibration — click on discs", on_click)
    print("Click on each disc colour. Press Q to quit.")
    while True:
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()