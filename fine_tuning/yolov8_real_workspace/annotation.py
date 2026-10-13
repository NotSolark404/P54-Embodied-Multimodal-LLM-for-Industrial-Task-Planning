"""Offline manual annotation preparation. No camera, model or robot imports."""
import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent / "annotation_work"
DATA = Path(__file__).resolve().parent / "dataset/data.yaml"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(source=ROOT / "Cam/raw_images", output=WORK):
    paths = sorted(Path(source).glob("*.png"))
    if not paths:
        raise ValueError("No PNG images to prepare")
    records, tiles = [], []
    for index, path in enumerate(paths, 1):
        image = cv2.imread(str(path))
        if image is None or image.shape != (376, 672, 3):
            raise ValueError(f"Invalid left ZED image: {path}")
        records.append(dict(source=str(path.resolve()), sha256=digest(path),
                            group="zed_20261013_scene_01", split=None, reviewed=False))
        tile = np.full((208, 336, 3), 240, np.uint8)
        tile[:188] = cv2.resize(image, (336, 188))
        cv2.putText(tile, f"{index:02d} {path.name[18:24]}", (5, 203),
                    cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 0), 1)
        tiles.append(tile)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "inventory.json").write_text(json.dumps(records, indent=2) + "\n")
    sheet = np.full((((len(tiles) + 4) // 5) * 208, 1680, 3), 240, np.uint8)
    for i, tile in enumerate(tiles):
        row, col = divmod(i, 5)
        sheet[row*208:(row+1)*208, col*336:(col+1)*336] = tile
    if not cv2.imwrite(str(output / "contact_sheet.jpg"), sheet):
        raise RuntimeError("Could not save contact sheet")
    return records


def yolo_row(class_id, box, width, height):
    x, y, w, h = box
    if w <= 0 or h <= 0 or min(x, y) < 0 or x+w > width or y+h > height:
        raise ValueError("Box must have positive size and be within the image")
    return f"{class_id} {(x+w/2)/width:.8f} {(y+h/2)/height:.8f} {w/width:.8f} {h/height:.8f}"


def annotate(index, work=WORK, data=DATA):
    config = yaml.safe_load(Path(data).read_text())
    if config.get("classes_confirmed") is not True:
        raise ValueError("Class names must be confirmed before manual draft annotation")
    names = config["names"]
    work = Path(work)
    records = json.loads((work / "inventory.json").read_text())
    if not 1 <= index <= len(records):
        raise ValueError("Image index is out of range")
    record = records[index-1]
    source = Path(record["source"])
    if digest(source) != record["sha256"]:
        raise ValueError("Original image changed since preparation")
    image = cv2.imread(str(source))
    drafts = work / "drafts" / source.stem
    drafts.mkdir(parents=True, exist_ok=True)
    revisions = sorted(drafts.glob("*.json"))
    boxes = json.loads(revisions[-1].read_text())["boxes"] if revisions else []
    selected = 0
    print("0/1: class; b: draw box then Enter; u: undo; c: clear; s: save draft; q: quit")
    print("Saved empty boxes means manually checked background, never automatic background.")
    try:
        while True:
            view = image.copy()
            for item in boxes:
                x, y, w, h = item["box"]
                cv2.rectangle(view, (x, y), (x+w, y+h), (0, 255, 0), 1)
                cv2.putText(view, names[item["class_id"]], (x, max(12, y)),
                            cv2.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 0), 1)
            title = "Manual annotation"
            cv2.putText(view, f"Selected: {names[selected]}", (5, 16),
                        cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 255, 255), 1)
            cv2.imshow(title, view)
            key = cv2.waitKey(100) & 255
            if key == ord('q') or cv2.getWindowProperty(title, cv2.WND_PROP_VISIBLE) < 1:
                break
            if ord('0') <= key < ord('0') + len(names):
                selected = key - ord('0')
            elif key == ord('b'):
                box = list(map(int, cv2.selectROI(title, image, showCrosshair=True)))
                if box[2] and box[3]:
                    boxes.append(dict(class_id=selected, box=box))
            elif key == ord('u') and boxes:
                boxes.pop()
            elif key == ord('c'):
                boxes.clear()
            elif key == ord('s'):
                from datetime import datetime, timezone
                revision = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ') + '_' + uuid4().hex
                rows = [yolo_row(b['class_id'], b['box'], image.shape[1], image.shape[0]) for b in boxes]
                payload = dict(source_sha256=record['sha256'], names=names, boxes=boxes,
                               reviewed=False, status="manual draft; requires review")
                (drafts / f'{revision}.json').write_text(json.dumps(payload, indent=2)+'\n')
                (drafts / f'{revision}.txt').write_text('\n'.join(rows) + ('\n' if rows else ''))
                print(f"Saved draft revision {revision}")
    finally:
        cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "annotate"])
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    else:
        annotate(args.index)


if __name__ == "__main__":
    main()
