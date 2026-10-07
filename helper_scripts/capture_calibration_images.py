"""Collect real images interactively; does not compute or validate calibration."""

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from physical_backend.vision.raspberry_pi_camera import RaspberryPiCamera


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory for real camera images")
    parser.add_argument("--count", type=int, default=15)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--camera-num", type=int, default=0)
    args = parser.parse_args(argv)
    if args.count <= 0:
        parser.error("--count must be positive")
    try:
        import cv2
        with RaspberryPiCamera(args.width, args.height, args.camera_num) as camera:
            args.output.mkdir(parents=True, exist_ok=False)
            for index in range(args.count):
                input(f"Position the calibration target for image {index + 1}/{args.count}; press Enter: ")
                frame = camera.capture()
                path = args.output / f"calibration_{index:03d}.png"
                if not cv2.imwrite(str(path), frame.bgr):
                    raise RuntimeError(f"Could not save {path}")
                print(f"Saved {path} ({frame.width}×{frame.height}, host timestamp {frame.timestamp})")
        print("Image collection complete. Calibration and hardware accuracy validation remain pending.")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Calibration image capture stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
