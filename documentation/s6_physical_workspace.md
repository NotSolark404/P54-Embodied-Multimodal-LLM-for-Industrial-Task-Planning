# Sprint 6: FOF physical workspace preparation

**Software preparation only. No real tray detection, measurements, calibration,
physical validation or robot movement has been performed by this change.**

## Repository inspection and integration decision

`simulation_backend/vision/scene_representation.py` reduces scenes to labels and
positions, discards other metadata and can substitute zero coordinates for missing
positions. `task_planner/planner.py` uses partial label matching, simulation-axis
spatial offsets and tray centres. Neither contract preserves compartment exclusions.
Passing this physical layout through those interfaces would lose essential restrictions.

The separate `physical_backend/workspace_config.json` and `workspace.py` therefore
have no imports or calls to the simulation, planner, controller or camera. Existing
PyBullet configuration, synthetic YOLO classes and weights remain unchanged. The
existing Raspberry Pi camera example remains a separate example; it is not the FOF
camera setup. The existing calibration loader validates numerical intrinsics and
rigid transforms but does not establish ZED compatibility or physical accuracy.

## Identity, restrictions and future measurements

Both white trays share workspace `fof_table`:

| Exact tray ID | Display name | Location in supplied photograph description |
| --- | --- | --- |
| `automatic_pick_1` | Automatic Pick 1 | Lower tray |
| `automatic_pick_2` | Automatic Pick 2 | Upper tray |

Each has `left_1`, `left_2`, `right_1`, `right_2`, qualified by tray ID, e.g.
`automatic_pick_1/right_1`. Side names refer only to the reference photograph.
The 1/2 suffixes are provisional identities within each side, **not an asserted
upper/lower order**; assign and annotate their actual locations in the lab.
No photograph file was supplied or inspected in this task. Its record remains null.
Never reassign tray identity by sorting live image coordinates; rotation, camera
viewpoint, or moving trays must not swap identities. Use confirmed labels/fiducials
and reference annotations; reject ambiguous or occluded identity.

Both right compartments have `usage: prohibited`, with picking and placement false.
The validator rejects attempts to relax these restrictions or add valid target
regions. Left compartments are candidates pending lab confirmation; both permissions
also remain false. All boundaries and regions are null, never zero-filled.

Future `boundary`, `valid_pick_region` and `valid_place_region` records accept a
perimeter of distinct 3D vertices, an explicit frame ID, metres and a measurement
record reference. These are measurement storage fields, not validated safe geometry.
Tray boundaries describe outer perimeters; compartment boundaries describe interiors;
valid regions must later be inset for walls, bumps, gripper/object footprint and
measurement uncertainty. No dimensions, margins, coordinates or tolerances are assumed.
Calibration/coordinate/validation record references are null until measured and reviewed.

`load_workspace()` validates the structure. `require_valid_target(workspace,
tray_id, compartment_id, "pick" or "place")` checks exact identities and restrictions,
and currently rejects **every** target. It rejects right compartments before checking
measurements, and missing geometry has an explicit error. Even populated geometry
cannot enable motion or make a left compartment valid in this preparation schema.

A future physical planner must call a completed guard for both source and destination,
retain the unconditional prohibited-compartment rule, and carry exact compartment IDs
through planning and execution. It must validate measured polygon topology, frame
consistency, containment, clearance, calibration freshness and physical approval,
then test actual proposed points/footprints (including any offsets) against valid
regions and exclusions. Never fall back to tray centres or fuzzy labels. This is an
integration contract and guard scaffold, not a claim that the unchanged planner
already enforces it. Version the schema when introducing physical readiness.

## ZED measurement and calibration procedure (pending lab work)

1. Dinith/Minh confirm the exact ZED model, serial number, SDK version, mounting,
   resolution, frame rate, depth mode, image stream/rectification, coordinate system,
   units and confidence settings. Record them with capture timestamps and calibration
   provenance. Confirm which two left interiors are usable and annotate all eight IDs
   on a preserved reference image. Record whether trays can move.
2. Capture synchronized images and depth with the confirmed SDK setup. The ZED depth
   API provides depth aligned with the left image; explicitly record coordinate units
   rather than assuming defaults. See [Stereolabs depth API](https://docs.stereolabs.com/docs/development/zed-sdk/modules/depth-sensing/using-the-api).
3. Retrieve intrinsics for the actual stream/resolution and preserve calibration
   records. Factory stereo calibration does not measure the camera-to-table or
   camera-to-robot installation. See [camera calibration](https://docs.stereolabs.com/docs/development/zed-sdk/modules/camera/camera-calibration).
4. Define a measured workspace origin and axes with a surveyed target/fiducials.
   Estimate camera-to-workspace extrinsics from correspondences covering both trays;
   document transform direction, units, handedness and reference camera frame.
   Establish workspace-to-robot extrinsics separately before any future physical
   integration. Image left/right is never robot left/right. See
   [ZED coordinate frames](https://docs.stereolabs.com/docs/development/zed-sdk/modules/positional-tracking/coordinate-frames).
5. Measure tray perimeters, each compartment interior, floor heights and wall/bump
   extents. Cross-check depth with independent physical measurements, especially on
   white surfaces, edges and occlusions. Reject invalid/low-confidence depth. Store
   perimeters in the documented metric frame; retain images and measurement records.
   Delineate separate pick/place regions only in confirmed left compartments.
6. Use independent check points across both trays to assess reprojection and metric
   error; record repeatability, depth coverage and uncertainty. Dinith/Minh must agree
   acceptance tolerances and gripper/object clearances before approval. Inspect region
   overlays including the excluded right compartments and test ambiguous identities,
   tray rotation/displacement, occlusion and missing depth. Invalidate records after
   camera/tray movement or relevant capture-setting changes until rechecked.

These steps describe future measurement work, not an implemented ZED adapter or an
instruction to move a robot. Physical motion remains outside this change.

## Software tests versus physical validation

Run `python3 -m pytest -q tests/test_physical_workspace.py`. Tests use the unmeasured
configuration and explicitly synthetic geometry; they check identities, restrictions,
missing measurements, malformed input and rejection behaviour. They do not establish
camera accuracy, tray detection performance, safe clearances or robot reachability.

Still needed from Dinith/Minh: reference photograph and ID annotations; confirmation
of left compartments; camera/SDK and mounting details; surveyed geometry and frame
transforms; object/gripper dimensions; agreed error/clearance limits; identity tracking
strategy for movable trays; and dated lab validation evidence. No real trays are
currently calibrated or authorised as targets.
