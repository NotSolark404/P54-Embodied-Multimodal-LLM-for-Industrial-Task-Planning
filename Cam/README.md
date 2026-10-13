# ZED left-camera image collection

From the repository root, using an environment with OpenCV and NumPy:

```sh
python -m Cam.collect_images --count 30 --interval 2
```

The script uses `cam.capture_frame()` unchanged, including the existing RTSP
URL/environment override, TCP transport, buffer drain, and confirmed 1344x376
side-by-side layout check. Each output is the 672x376 left view. Unexpected
layouts stop collection rather than being cropped without verification.

Lossless PNG images are saved in `Cam/raw_images/`, which is Git-ignored, as are
`Cam/test_frame*.jpg`. Filenames contain host UTC time after capture and a UUID;
exclusive file creation prevents overwriting even if a name collides. These are
unannotated images for later YOLO annotation, not sensor-raw data. RGB is converted
back to BGR for correct OpenCV file encoding. Images are not resized.

`--count` must be positive; `--interval` is a finite, non-negative delay after
saving each image except the last (not a guaranteed frame rate). Each capture
opens and releases the existing RTSP connection. Ctrl+C or a capture/write error
stops the batch, retaining completed files. The existing RTSP open/read calls
can block until OpenCV returns; there is no new network timeout guarantee.

Use `--output /path/to/images` to change the destination. Custom destinations
inside the repository need their own Git ignore rule. Do not force-add raw
captures. No robot commands, annotation, training, calibration, or depth
estimation are performed. Cropping alone provides no depth information.

Hardware-free checks:

```sh
python -m pytest Cam/test_cam.py Cam/test_collect_images.py -q
```

## Initial existing-model baseline

Run `python -m Cam.run_baseline` in an environment with Ultralytics installed.
It performs inference on all PNGs in `Cam/raw_images/` using the existing
workspace `best.pt`, CPU, confidence 0.25, IoU 0.45 and inference size 640.
Each run creates a unique Git-ignored `Cam/baseline_predictions/` subdirectory
with annotated images, per-image JSON (including empty detections), a confidence
CSV and a report. The model SHA-256 is checked before and after inference.
This is an initial baseline, not real-workspace training or measured accuracy.
