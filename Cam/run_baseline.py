"""Inference-only initial real-image baseline; no training or calibration."""
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "fine_tuning/yolov8n_p54_finetuning/yolov8n_p54_workspace_final/weights/best.pt"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    import cv2
    import ultralytics
    from ultralytics import YOLO

    sources = sorted((ROOT / "Cam/raw_images").glob("*.png"))
    if not sources:
        raise RuntimeError("No PNG images found in Cam/raw_images")
    if not WEIGHTS.is_file():
        raise FileNotFoundError(WEIGHTS)
    original_hash = sha256(WEIGHTS)
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
    output = ROOT / "Cam/baseline_predictions" / run
    output.mkdir(parents=True, exist_ok=False)
    model = YOLO(str(WEIGHTS))
    settings = dict(conf=0.25, iou=0.45, imgsz=640, device="cpu", verbose=False, save=False)
    records = []
    with (output / "confidence_scores.csv").open("x", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["image", "class_id", "class_name", "confidence", "x1", "y1", "x2", "y2"])
        for source in sources:
            result = model.predict(source=str(source), **settings)[0]
            detections = []
            for box in result.boxes:
                class_id = int(box.cls.item())
                confidence = float(box.conf.item())
                xyxy = box.xyxy[0].tolist()
                name = result.names[class_id]
                detections.append(dict(class_id=class_id, class_name=name,
                                       confidence=confidence, xyxy=xyxy))
                writer.writerow([source.name, class_id, name, confidence, *xyxy])
            if not detections:
                writer.writerow([source.name, "", "", "", "", "", "", ""])
            prediction = output / source.name
            if not cv2.imwrite(str(prediction), result.plot()):
                raise RuntimeError(f"Could not save {prediction}")
            records.append(dict(image=source.name, source_sha256=sha256(source),
                                shape=list(result.orig_shape), detections=detections))
            print(f"{source.name}: {len(detections)} detections", flush=True)
    final_hash = sha256(WEIGHTS)
    if final_hash != original_hash:
        raise RuntimeError("Model checksum changed during inference")
    report = dict(status="Initial baseline, not real-workspace training",
                  weights=str(WEIGHTS.relative_to(ROOT)), weights_sha256=original_hash,
                  weights_unchanged=True, ultralytics_version=ultralytics.__version__,
                  settings=settings, class_names=model.names, images=records)
    (output / "predictions.json").write_text(json.dumps(report, indent=2) + "\n")
    detections = [d for r in records for d in r["detections"]]
    counts = {}
    for detection in detections:
        counts[detection["class_name"]] = counts.get(detection["class_name"], 0) + 1
    summary = ["# Initial real-image YOLO baseline", "",
               "This is an initial baseline using existing weights, not real-workspace training.",
               f"Weights: `{report['weights']}`", f"SHA-256 (unchanged): `{original_hash}`",
               f"Ultralytics: {ultralytics.__version__}; CPU; confidence 0.25; IoU 0.45; image size 640.",
               f"Images: {len(records)}; detections: {len(detections)}; images without detections: "
               f"{sum(not r['detections'] for r in records)}.",
               f"Detection counts by class: {json.dumps(counts, sort_keys=True)}."]
    if detections:
        summary.append(f"Confidence range: {min(d['confidence'] for d in detections):.4f}–"
                       f"{max(d['confidence'] for d in detections):.4f}.")
    summary.extend(["", "Annotated PNGs accompany predictions.json and confidence_scores.csv.",
                    "Empty CSV detection fields mean no predictions above the threshold.",
                    "Confidence scores are model outputs, not measured accuracy. No ground-truth "
                    "annotations were supplied, so precision, recall and mAP were not calculated.",
                    "No training, calibration, depth estimation, robot control or simulation was performed."])
    (output / "REPORT.md").write_text("\n\n".join(summary) + "\n")
    print(f"Results: {output}")


if __name__ == "__main__":
    main()
