# S6-2 manual annotation — current preparation

The 30 original ZED left images were inspected in a contact sheet. All are
672×376, from 2026-10-13 03:27:49–03:31:13 UTC. The workspace and camera view
are largely unchanged; the person, arm and some items vary. These are one
conservative scene group, `zed_20261013_scene_01`, not 30 independent scenes.
The synthetic model's 30 predictions are unverified predictions, not labels.

## Physical classes and approval

The user confirmed this ordered two-class map:

| ID | Name | Intended meaning |
|---|---|---|
| 0 | automatic_pick_tray | Both physical Automatic Pick trays, each with its own box |
| 1 | electronic_component | The physical electronic component, identified manually by the annotator |

`names: [automatic_pick_tray, electronic_component]` and
`classes_confirmed: true` are now set. IDs are fixed: do not reorder them.
Manual draft annotation is enabled. The annotator must identify the actual
component and tray boundaries; no object identity or box is inferred from model
predictions. `object_definitions_confirmed: false` remains pending that review,
and `annotations_confirmed: false` keeps dataset acceptance/training blocked.
No seven-class synthetic mapping is copied.

## Prepared local material

`fine_tuning/yolov8_real_workspace/annotation_work/` is Git-ignored and contains
an inventory of all 30 source paths, SHA-256 checksums, pending review states,
unassigned splits and a contact sheet. Originals remain in `Cam/raw_images/`.
Nothing has been copied into train/val/test and no labels have been generated.
Preparation refuses to overwrite an existing working directory.

## Open the tool and draw manual drafts

Run this exact command from the repository root, using the project environment
with desktop OpenCV, NumPy and PyYAML:

```sh
venv/bin/python -m fine_tuning.yolov8_real_workspace.annotation annotate --index 1
```

Do not rerun `prepare`: use the existing inventory and drafts. Existing saved
revisions are preserved; opening an image loads its latest draft.

Indices 1–30 follow the numbered contact sheet and sorted inventory. The tool
refuses to open for annotation until class and object definitions are confirmed.
It reads image files only, checks their hashes, and imports no model, camera,
simulation or robot controller. It sends no motion commands. The GUI has not
been launched during preparation; check interaction on the lab desktop.

- Press `0` for tray or `1` for component.
- Press `b`, drag a tight axis-aligned box, and press Enter to accept; Escape
  cancels that box. Repeat for every visible instance, including both trays.
- `u` removes the latest box; `c` clears boxes for redrawing. `q` exits.
- `s` saves a new draft revision, with pixel boxes in JSON and normalized YOLO
  rows in TXT. It does not approve the annotation or populate dataset splits.
- Reopening an index loads its latest revision. Correct boxes with undo/clear
  and redraw, then save another revision; old revisions remain available.

Box the visible physical object's outer extent, excluding surrounding table,
shadows and unrelated supports. Do not box tray slots individually. For partial
occlusion, box visible extent consistently; skip ambiguous objects/images for
review rather than inventing hidden boundaries. Do not label the robot, person,
monitor or workstation under either target class. Inspect at full resolution.
An empty saved draft is appropriate only after manually verifying no target is
visible; an unlabelled or uncertain frame is never automatically background.

A reviewer must reopen every selected image, inspect all boxes/classes, correct
missed or incorrect objects, and record reviewer/date and accepted revision in a
review log. JSON drafts intentionally remain `reviewed: false`; after actual
review record approval explicitly. No predictions are loaded by this tool.

## Prevent split leakage

Keep ALL current 30 images together, even if some look less similar. Do not
randomly split this burst. Select useful representatives for annotation after
manual duplicate review; retain excluded originals and record exclusions.
Collect independent scene/session groups for validation and preferably test.
If a later session repeats a near-identical scene, merge its group with this one;
a timestamp alone does not establish independence. Review contact sheets across
groups before assigning splits. This is a conservative grouping policy, not a
claim that a similarity algorithm can find every near-duplicate.

Only after review, copy accepted images and corresponding accepted revision TXT
files into matching `dataset/images/{split}` and `dataset/labels/{split}` paths.
Do not move originals or use draft revision filenames as label stems. Make
`dataset/split_groups.json` a mapping from each image's dataset-relative path to
its audited group and source file checksum, e.g.:

```json
{"images/train/example.png": {"group": "zed_20261013_scene_01", "sha256": "actual SHA-256"}}
```

The validator requires exact manifest coverage, matching hashes and one split
per group for this scaffold. It also rejects exact decoded duplicates. Group
assignments need human audit; invented separate group IDs defeat this protection.
No automated split/export is offered for the current single-group collection.
At least one separate validation group is still required.

## Acceptance and remaining work

Identify the component and tray boundaries; complete physical class definitions;
select representative frames; draw and review annotations; collect independent
validation/test scenes; audit group assignments; then confirm annotations in YAML
and run the dataset validator. Training remains blocked by unconfirmed physical definitions,
annotations and an empty dataset. Do not run training until these are confirmed
and the user requests it. No calibration, depth or robot execution is implied.

Tests: `venv/bin/python -m pytest tests/test_real_image_annotation.py tests/test_real_workspace_dataset.py Cam/test_cam.py Cam/test_collect_images.py -q`.

## Saved-label review and train-only staging (2026-10-13)

Two images have saved manual annotations; the remaining 28 are not labelled and
were excluded, not treated as background. Assistant visual review compared each
saved box against its original image. Both contain two white tray boxes and the
small red component next to the monitor. In image 2, box 3 incorrectly used class
0; a new revision changes it to class 1, consistent with image 1. Coordinates were
retained. Original draft revisions and source images remain unchanged.

This is assistant visual review of user-drawn labels, not final human acceptance.
Review the red component identity and tightness of the tray boxes, especially the
outer rims. `annotation_work/selected_review.json` records the selected revisions,
reviewer, reason and pending human confirmation. Open indices 1 and 2 with the
manual tool to correct further; index 2 loads the new corrected revision.

The selected two images and six boxes (four trays, two components) are copied to
`dataset/images/train/` and `dataset/labels/train/`. The entire scene group remains
in train; val/test are empty. `dataset/split_groups.json` records source hashes and
group assignments; `dataset/annotation_review.json` records selected revisions.
`object_definitions_confirmed` and `annotations_confirmed` remain false. Thus this
is a staged training subset, not a ready-to-train dataset. No model was loaded.

The module `prepare_reviewed_dataset` exports only explicit reviewed revisions,
checks source hashes and JSON/TXT agreement, and refuses existing destination
files. It does not create new boxes or random splits. The current export has
already run; do not rerun it into the same dataset. If drafts are corrected again,
review them and prepare a new version before replacing accepted dataset labels.

Remaining: human review of selected revisions and physical boundaries; annotate
more selected images as needed; collect independently varied validation/test
scenes and review group assignments. Never split these 30 near-identical images
across train and validation just to satisfy the validator. Training remains off.
