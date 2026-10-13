"""Collect unannotated left-camera RGB images without moving any hardware."""
import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import sys
import time
from uuid import uuid4

import cv2
import numpy as np

if __package__:
    from . import cam
else:
    import cam

DEFAULT_OUTPUT = Path(__file__).resolve().parent / "raw_images"


def save_image(frame_rgb, output):
    """Encode lossless PNG and create a new file exclusively (never overwrite)."""
    height, width = cam.CONFIRMED_STEREO_SHAPE
    if (not isinstance(frame_rgb, np.ndarray)
            or frame_rgb.dtype != np.uint8
            or frame_rgb.shape != (height, width // 2, 3)):
        raise RuntimeError("Invalid captured RGB left image: unexpected dimensions or dtype")
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("Failed to encode captured image")
    # Host UTC time after capture, not a camera exposure timestamp.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    path = Path(output) / f"zed_left_{stamp}_{uuid4().hex}.png"
    # Exclusive creation protects even against a timestamp/UUID collision.
    with path.open("xb") as handle:
        try:
            handle.write(encoded.tobytes())
            handle.flush()
        except BaseException:
            path.unlink(missing_ok=True)
            raise
    return path


def collect_images(count=10, interval=1.0, output=DEFAULT_OUTPUT):
    """Capture a finite batch; stop on failure and preserve completed images."""
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise ValueError("count must be a positive integer")
    if not math.isfinite(interval) or interval < 0:
        raise ValueError("interval must be finite and non-negative")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    saved = []
    for index in range(count):
        frame = cam.capture_frame()
        path = save_image(frame, output)
        saved.append(path)
        print(f"Saved {index + 1}/{count}: {path}", flush=True)
        if index + 1 < count:
            time.sleep(interval)
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10, help="number of images (default: 10)")
    parser.add_argument("--interval", type=float, default=1.0,
                        help="seconds to wait between captures (default: 1)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="output directory (default: Cam/raw_images)")
    args = parser.parse_args(argv)
    try:
        collect_images(args.count, args.interval, args.output)
    except KeyboardInterrupt:
        print("Collection interrupted; completed images are retained.", file=sys.stderr)
        return 130
    except (ValueError, RuntimeError, OSError, cv2.error) as exc:
        print(f"Collection stopped: {exc}. Completed images are retained.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
