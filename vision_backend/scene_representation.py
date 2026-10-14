"""
vision_backend/scene_representation.py
---------------------------------------
Scene provider for the pipeline's Vision Lookup stage.

Two modes (set VISION_MODE in .env):
    VISION_MODE=json  (default) — reads static JSON from disk
    VISION_MODE=live            — captures ZED camera frame and runs colour detector

Public interface:
    get_current_scene() -> dict

Output format (same regardless of mode):
    {
        "objects": [
            {"label": "grey tray",         "position": [cx, cy]},
            {"label": "bottom tray slot 1", "position": [cx, cy]},
            ...
        ]
    }
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_SCENE_FILE = Path(__file__).resolve().parent / "scene_representation.json"
_VISION_MODE        = os.getenv("VISION_MODE", "json").strip().lower()


def get_current_scene() -> dict:
    """
    Return a planner-compatible scene dict.

    In 'json' mode: reads vision_backend/scene_representation.json
    In 'live' mode: captures ZED camera frame and runs colour detector
    """
    if _VISION_MODE == "live":
        return _get_live_scene()
    else:
        return _get_json_scene()


# ── JSON mode ──────────────────────────────────────────────────────────────────

def _get_json_scene() -> dict:
    scene_file = Path(os.getenv("VISION_SCENE_FILE", str(_DEFAULT_SCENE_FILE)))

    if not scene_file.exists():
        raise FileNotFoundError(
            f"Scene file not found: {scene_file}. "
            f"Set VISION_SCENE_FILE in .env or ensure "
            f"vision_backend/scene_representation.json exists."
        )

    try:
        with open(scene_file, encoding="utf-8") as f:
            raw = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Scene file is not valid JSON: {scene_file} — {e}") from e

    if "objects" not in raw:
        raise ValueError(f"Scene file missing 'objects' key: {scene_file}")

    scene = _convert(raw)
    logger.info(
        f"[scene_representation] JSON: loaded {len(scene['objects'])} objects "
        f"from {scene_file}"
    )
    return scene


def _convert(raw: dict) -> dict:
    """
    Normalise raw JSON into planner-compatible scene format.
    Accepts both:
        {"label": "x", "position": [cx, cy]}
        {"label": "x", "bounding_box": [x, y, w, h]}   ← converts to centre
    """
    objects = []
    for obj in raw["objects"]:
        label = obj["label"]
        if "position" in obj:
            position = list(obj["position"])[:2]
        elif "bounding_box" in obj:
            x, y, w, h = obj["bounding_box"]
            position = [x + w / 2, y + h / 2]
        else:
            position = [0.0, 0.0]
        objects.append({"label": label, "position": position})
    return {"objects": objects}


# ── Live mode ──────────────────────────────────────────────────────────────────

def _get_live_scene() -> dict:
    """
    Capture a frame from the ZED RTSP stream and run the colour detector.
    Returns the same format as JSON mode.
    """
    try:
        from camera_backend.zed_rstp import capture_frame
        from vision_backend.colour_detector import detect

        frame   = capture_frame()
        results = detect(frame)   # list of {"label": str, "bounding_box": [x,y,w,h]}

        objects = []
        for obj in results:
            x, y, w, h = obj["bounding_box"]
            objects.append({
                "label":    obj["label"],
                "position": [x + w / 2, y + h / 2],
            })

        logger.info(
            f"[scene_representation] LIVE: detected {len(objects)} objects: "
            f"{[o['label'] for o in objects]}"
        )
        print(f"  [Vision] Detected: {[o['label'] for o in objects]}")
        return {"objects": objects}

    except Exception as e:
        logger.warning(f"[scene_representation] Live capture failed: {e} — falling back to JSON")
        print(f"  [Vision] ⚠ Live capture failed ({e}), falling back to JSON scene")
        return _get_json_scene()