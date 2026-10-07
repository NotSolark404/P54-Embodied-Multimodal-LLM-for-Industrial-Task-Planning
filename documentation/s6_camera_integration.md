# S6-1: physical-camera software preparation

**No physical calibration or hardware validation has yet been performed.**
The Raspberry Pi camera is not available. Test fixtures contain arbitrary TEST
values only; they are not calibration measurements or accuracy evidence.

## Existing simulation limitation

`simulation_backend/vision/camera.py` renders BGR, depth and body-ID segmentation
through PyBullet. `YOLODetector.detect()` uses bounding-box centres to read those
body IDs, then gets labels and cached 3D positions from the simulation registry.
Ground truth can fill missed detections. Consequently, success in simulation
does not establish physical object recognition or physical localisation.
The existing Camera, YOLODetector, Simulation and `get_current_scene()` are unchanged.

## Implemented foundation

- `physical_backend/vision/camera_base.py`: validated uint8 RGB/BGR frames,
  dimensions, host Unix timestamps, explicit depth/segmentation capability flags,
  and start/capture/close/context-manager contract. There are no fake depth or
  segmentation fields. Timestamps describe capture completion, not exposure time.
- `raspberry_pi_camera.py`: lazy Picamera2 import, clear unavailable-library/device
  errors, explicit lifecycle, capture validation and cleanup. RGB888 is requested
  in Picamera2's BGR byte order for OpenCV. Colour order and negotiated resolution
  still require verification on the actual camera. There is no simulation fallback.
- `calibration.py`: JSON calibration loading and structural/numeric validation.
  `load_calibration(None)` returns `None` (uncalibrated). A specified nonexistent
  file raises `FileNotFoundError`; malformed calibration raises `ValueError`.
- `physical_backend/camera_config.example.yaml`: illustrative capture settings
  and an unset calibration path. It is a reference configuration, not an automatic
  runtime configuration loader; the capture utility accepts CLI settings.
- `helper_scripts/capture_calibration_images.py`: interactive real-image collection
  into a new directory, with cleanup on completion/error/interruption. It does
  not compute calibration. Interrupted collections may leave partial image sets.
- Software tests cover frame validation, missing dependencies, lifecycle cleanup,
  missing/malformed calibration and clearly labelled TEST calibration values.

Picamera2/libcamera is an optional target-Pi dependency. It is deliberately not
added to the shared requirements, so desktop simulation imports remain independent.

## Calibration file contract

Version 1 is a JSON object with these keys (no measured file is supplied):

| Key | Meaning |
|---|---|
| `schema_version` | Integer 1 |
| `image_width`, `image_height` | Positive calibrated image dimensions |
| `camera_matrix` | 3×3 pinhole intrinsic matrix, pixel units |
| `distortion_coefficients` | OpenCV pinhole coefficient vector, length 4/5/8/12/14; not a fisheye model |
| `target_frame` | `robot` or `workspace` |
| `camera_to_target` | Rigid 4×4 transform, `target_point = T @ camera_point`, translation in metres |

Camera coordinates use the OpenCV convention: X right, Y down, Z forward.
The measured target coordinate axes and origin must be documented with the actual
setup. A workspace transform alone is not a robot-base transform. Intrinsics and
extrinsics must match the actual mounting, lens configuration and capture mode.
The loader checks shape, finite numbers, positive focal lengths and rigid rotation;
passing it does not establish measurement accuracy. Version 1 expects a complete
record: partial calibration must not be passed as planner-ready calibration.

## Planned procedure after hardware arrives

1. Install the target Pi camera stack; verify connection, capture, RGB/BGR order,
   resolution and reliable shutdown. Record camera/lens and capture settings.
2. Measure a calibration target's dimensions. Collect varied target positions,
   tilts and coverage across the image; avoid blur and keep the lens setup fixed.
3. Example collection command (requires real hardware):
   `python helper_scripts/capture_calibration_images.py --output calibration_images/session_01 --count 15`
   The count is a collection convenience, not an accuracy acceptance criterion.
4. Estimate intrinsics/distortion with OpenCV using actual target measurements.
   Inspect corner detections, reprojection residuals and independent held-out views.
   Calibration computation tooling is not implemented in this foundation.
5. Measure camera-to-workspace/robot alignment using known target-frame points;
   validate transform direction, units, axes and independent reference points.
6. Save measured parameters using the schema and evaluate task-appropriate position
   errors. Repeat after changes to mounting, lens or capture configuration.

## Pending work and boundaries

Hardware capture, real image collection, intrinsic/extrinsic measurements and
accuracy validation are blocked by unavailable hardware. No calibration values
are supplied outside TEST fixtures. Software-only mocked tests are not substitutes.

Class-based physical YOLO detection, localisation, calibration computation and
scene-provider integration are future work, outside this foundation. An RGB image
and intrinsic matrix alone do not determine world XYZ; later localisation needs
measured geometry/depth and explicit assumptions. Missing positions must never
be replaced by zeros or simulation registry/ground-truth values. Existing
`get_current_scene()` continues to use simulation exclusively.
