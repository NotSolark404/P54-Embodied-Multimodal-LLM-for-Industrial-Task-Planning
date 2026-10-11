# S6-2 — real workspace YOLOv8 training preparation

Status: software preparation only. **No real-image training, real-image accuracy
measurement, physical calibration or camera validation has been completed.**
The lab has a webcam-like camera; its model, driver and capture requirements remain
unconfirmed. This workflow consumes image files and does not assume Picamera2 or
any other camera API. S6-1's Raspberry Pi adapter is not used here.

## Existing synthetic assets (unchanged)

`fine_tuning/yolov8n_p54_finetuning/generate_yolo_synthetic_dataset.py` renders
PyBullet frames and derives bounding boxes from segmentation masks. The existing
`datasets/p54_workspace/data.yaml` names seven synthetic classes:

| ID | Synthetic class |
|---|---|
| 0 | red block |
| 1 | blue block |
| 2 | green block |
| 3 | yellow block |
| 4 | left tray |
| 5 | right tray |
| 6 | workstation |

The checked workspace contains 240 training images/labels and 60 validation
images/labels, with no test split. `yolov8n_p54_workspace_final/args.yaml` records
YOLOv8n training for 5 epochs, batch 8, image size 640, CPU. The run contains
`weights/best.pt` and `weights/last.pt`. No standalone synthetic training script
was found; generation and verification scripts and saved training arguments exist.
`verify_yolo_workspace.py` tests raw simulation detections, which still obtain
identity from segmentation and position from the simulation registry. Its results
must not be treated as real-camera recognition/localisation evidence.

## Separate physical dataset

All new tooling lives in `fine_tuning/yolov8_real_workspace/`:

```text
dataset/
  data.yaml             # names: [], classes_confirmed: false
  images/{train,val,test}/
  labels/{train,val,test}/
validate_dataset.py
train.py
runs/                   # created only when training is actually requested
```

Only empty directory markers and configuration are supplied. No images or labels
are supplied. The physical class list requires confirmation by Dinith/the lab.
Review the real objects and annotation rules before setting `names` to an ordered
list of agreed names and `classes_confirmed: true`. IDs are list indices starting
at zero; a contiguous integer-keyed mapping also works. Do not assume the seven
synthetic classes match physical objects. In particular, review whether left/right
tray identity is semantic or just a workspace position. Freeze/version the class
map before annotation; never silently reorder an already-labelled dataset.

## Collect and label

1. Confirm the camera model, supported capture software, image resolution and colour
   format. Verify capture on the lab machine; camera-specific capture implementation
   is deferred. Geometric calibration is separate from 2D detector training.
2. Collect actual workspace photos covering lighting, viewpoints, object orientations,
   distances, clutter, partial occlusion and background-only scenes. Include the
   intended deployment view. Retain original images and record camera/settings,
   session ID, object inventory and collection date in an external collection log.
3. Split by capture session/scene before augmentation. Keep adjacent video frames
   and similar poses in one split. Reserve a held-out test set, separate from train
   and validation. Exact-duplicate checking cannot detect all near-duplicate leakage.
4. Manually annotate tight axis-aligned boxes using a lab-approved annotation tool
   exporting YOLO detection format. Review class consistency, occlusion rules and
   missed objects. Use one `.txt` per image, with matching relative path and stem.
   Each row is `class_id x_center y_center width height`, normalized to image size.
   This project's validator requires an explicit empty file for reviewed background
   images so missing annotations are not silently treated as negatives.
5. Place JPG/JPEG/PNG/BMP files under images and reviewed annotations under labels.
   Nested session directories are supported in matching image/label trees. Do not
   reuse one image stem with different extensions in the same directory.

## Validate and train later

Run from the repository root using the project environment (NumPy/OpenCV, PyYAML;
training additionally requires Ultralytics and compatible PyTorch):

```sh
python fine_tuning/yolov8_real_workspace/validate_dataset.py
python fine_tuning/yolov8_real_workspace/validate_dataset.py --require-test
```

The empty scaffold intentionally fails with an unconfirmed-class error. Once classes
are confirmed, checks cover image decoding, empty required splits, missing/orphan
labels, integer class IDs, finite normalized boxes inside image bounds, class
coverage in training and identical decoded image content (including across splits).
Train/val must contain images. Test may be empty during preparation; `--require-test`
requires it. Inspect per-class counts for validation/test coverage as well.
These checks do not establish semantic annotation quality, real-image provenance,
or adequate dataset size; those require human review.

After real images and annotations pass review:

```sh
python fine_tuning/yolov8_real_workspace/train.py --name lab_session_01 --epochs 50 --imgsz 640 --batch 8 --device cpu
```

These are configurable starting settings, not tuned values or accuracy promises.
The default starting checkpoint is the existing generic
`simulation_backend/vision/detection_weight/yolov8n.pt`, read only. It does not use
the synthetic fine-tuned `best.pt`. `--weights` accepts a local YOLOv8 detection
checkpoint; the script requires the file to exist rather than auto-downloading it.
Validation happens before importing/loading the model. Confirmed data paths are
resolved relative to data.yaml, then written to a separate `data.resolved.yaml`
inside the new run. Outputs stay under `fine_tuning/yolov8_real_workspace/runs/`.
Existing run names are rejected, including partially failed runs; choose a new name.
No simulation configuration, class mapping or weight selection is updated.

## Evaluate and record evidence later

Use validation during development and freeze model/settings before final test
evaluation. First run validation with `--require-test`. If a test split was added
after training, create an evaluation copy of the resolved YAML with its absolute
dataset root and `test: images/test`; preserve the original training manifest.
For a run whose resolved YAML already includes the test split:

```sh
yolo detect val model=fine_tuning/yolov8_real_workspace/runs/lab_session_01/weights/best.pt data=fine_tuning/yolov8_real_workspace/runs/lab_session_01/data.resolved.yaml split=test project=fine_tuning/yolov8_real_workspace/runs name=lab_session_01_test
```

Record actual precision, recall, mAP50, mAP50–95, per-class results and confusion
matrix; inspect false positives/negatives and confidence thresholds. Report dataset
version/counts, split-session assignments, class-map version, weights, package
versions, seed and device with measured results. Measure inference latency separately
on the intended lab computer/camera. Detection accuracy alone does not validate
3D localisation or robot execution. No accuracy numbers are supplied here.

## Tests and outstanding work

`tests/test_real_workspace_dataset.py` uses in-memory TEST annotations, mocked paths
and decoder/model doubles; it creates no dataset images, label files or model
weights. Tests cover class confirmation, malformed labels, missing/orphan labels,
corrupt images, duplicate leakage, split requirements, training refusal and output
isolation. These are software checks only.

Pending: camera identification/setup; real object/class confirmation; real collection,
annotation and split review; actual YOLOv8 training and held-out evaluation. No
physical camera integration or simulation-to-physical detector switch is made.

Format/API references: [Ultralytics detection datasets](https://docs.ultralytics.com/datasets/detect/),
[training](https://docs.ultralytics.com/modes/train/), and
[validation](https://docs.ultralytics.com/modes/val/).
