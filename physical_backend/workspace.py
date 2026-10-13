"""FOF workspace metadata and fail-closed target validation; no robot interface."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

DEFAULT_CONFIG = Path(__file__).with_name("workspace_config.json")
SLOTS = {"left_1", "left_2", "right_1", "right_2"}
TRAYS = {
    "automatic_pick_1": ("Automatic Pick 1", "lower"),
    "automatic_pick_2": ("Automatic Pick 2", "upper"),
}


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Region(Record):
    """Measured 3D perimeter in an explicitly named metric frame; not approval."""

    frame_id: str = Field(min_length=1)
    units: Literal["metres"]
    vertices: list[list[FiniteFloat]] = Field(min_length=3)
    measurement_record: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_vertices(self):
        if any(len(point) != 3 for point in self.vertices):
            raise ValueError("Region vertices require three measured coordinates")
        if len({tuple(point) for point in self.vertices}) != len(self.vertices):
            raise ValueError("Region vertices must be distinct (do not repeat closing vertex)")
        return self


class Compartment(Record):
    id: str
    reference_slot: Literal["left_1", "left_2", "right_1", "right_2"]
    usage: Literal["candidate_pending_lab_confirmation", "prohibited"]
    pick_allowed: Literal[False]
    place_allowed: Literal[False]
    reason: str = Field(min_length=1)
    boundary: Region | None
    valid_pick_region: Region | None
    valid_place_region: Region | None

    @model_validator(mode="after")
    def enforce_restrictions(self):
        right = self.reference_slot.startswith("right_")
        expected = "prohibited" if right else "candidate_pending_lab_confirmation"
        if self.usage != expected:
            raise ValueError("Compartment usage conflicts with reference-side restriction")
        if right and (self.valid_pick_region is not None or self.valid_place_region is not None):
            raise ValueError("Prohibited compartments cannot have valid target regions")
        return self


class Tray(Record):
    id: Literal["automatic_pick_1", "automatic_pick_2"]
    name: str
    reference_photo_location: Literal["lower", "upper"]
    boundary: Region | None
    compartments: list[Compartment] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def check_identity(self):
        if (self.name, self.reference_photo_location) != TRAYS[self.id]:
            raise ValueError("Tray identity does not match reference photograph description")
        if {c.reference_slot for c in self.compartments} != SLOTS:
            raise ValueError("Each tray requires all four unique reference slots")
        if any(c.id != f"{self.id}/{c.reference_slot}" for c in self.compartments):
            raise ValueError("Compartment identifiers must be qualified by their tray")
        return self


class Camera(Record):
    manufacturer: Literal["Stereolabs"]
    family: Literal["ZED"]
    model: str | None
    serial_number: str | None
    sdk_version: str | None
    sdk_configuration_record: str | None


class Measurements(Record):
    reference_photo_record: str | None
    coordinate_frame_record: str | None
    camera_calibration_record: str | None
    camera_to_workspace_record: str | None
    workspace_to_robot_record: str | None
    lab_validation_record: str | None


class Workspace(Record):
    schema_version: Literal[1]
    workspace_id: Literal["fof_table"]
    status: Literal["preparation_only"]
    orientation_basis: Literal["reference_photo_only_not_robot_axes"]
    camera: Camera
    measurements: Measurements
    trays: list[Tray] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def check_trays(self):
        if {tray.id for tray in self.trays} != set(TRAYS):
            raise ValueError("Both unique Automatic Pick tray identifiers are required")
        return self


class TargetRejected(ValueError):
    """Target is not authorised by the physical workspace contract."""


def load_workspace(path: str | Path = DEFAULT_CONFIG) -> Workspace:
    """Missing files/fields and invalid metadata are errors, never default geometry."""
    return Workspace.model_validate_json(Path(path).read_text(encoding="utf-8"))


def require_valid_target(
    workspace: Workspace, tray_id: str, compartment_id: str, action: str
) -> None:
    """Guard for a future physical planner. V1 deliberately authorises no targets.

    Exact IDs only. Revalidate mutable nested collections on every call. A future
    integration must retain the prohibition check and add measured-point containment,
    calibration freshness, lab approval and collision checks before allowing targets.
    """
    workspace = Workspace.model_validate(workspace.model_dump())
    if action not in ("pick", "place"):
        raise TargetRejected("Unknown action; expected pick or place")
    tray = next((t for t in workspace.trays if t.id == tray_id), None)
    compartment = next((c for c in tray.compartments if c.id == compartment_id), None) if tray else None
    if compartment is None:
        raise TargetRejected("Unknown exact tray/compartment identifier")
    if compartment.usage == "prohibited":
        raise TargetRejected("Raised-bump compartment is prohibited for picking and placement")
    if tray.boundary is None or compartment.boundary is None or getattr(
        compartment, f"valid_{action}_region"
    ) is None:
        raise TargetRejected("Missing physical measurements; target is unavailable")
    raise TargetRejected("Preparation only: physical calibration and target validation are not implemented")
