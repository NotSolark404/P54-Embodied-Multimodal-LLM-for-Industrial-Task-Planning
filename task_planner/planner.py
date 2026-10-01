"""
task_planner/planner.py
-----------------------
PB7 (Sprint 2) + PB7-SP + PB7-MULTI (Sprint 3) + DISC-1 (Sprint 5)

Sprint 5 additions:
    - Disc and tray slot support: "pick up the red disc from slot 2"
    - Colour-only matching: "red" matches "red disc" in scene
    - Slot reference matching: "slot 0" finds disc in slot 0
    - Workspace boundary clamping: spatial offsets stay within robot limits
    - _plan_disc_pick(): pick disc from slot, place in target slot or tray
"""

import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_backend.schema import ParsedInstruction, ActionType
from simulation_backend.action_schema import ActionPlan, RobotCommand, CommandType, Position

logger = logging.getLogger(__name__)

# ── Spatial offset map ─────────────────────────────────────────────────────────
SPATIAL_OFFSETS: dict[str, tuple[float, float]] = {
    "left of":     (-0.15,  0.0),
    "left":        (-0.15,  0.0),
    "right of":    ( 0.15,  0.0),
    "right":       ( 0.15,  0.0),
    "near":        ( 0.08,  0.08),
    "next to":     ( 0.12,  0.0),
    "on top of":   ( 0.0,   0.0),
    "in front of": ( 0.0,  -0.15),
    "behind":      ( 0.0,   0.15),
    "in":          ( 0.0,   0.0),
    "above":       ( 0.0,   0.0),
    "below":       ( 0.0,   0.0),
}

DEFAULT_OFFSET = (0.10, 0.0)

# ── Workspace bounds (metres) ─────────────────────────────────────────────────
# Clamp all computed positions to these limits before sending to robot
WORKSPACE_X_MIN = 0.15
WORKSPACE_X_MAX = 0.75
WORKSPACE_Y_MIN = -0.45
WORKSPACE_Y_MAX =  0.45


# ── Scene helpers ──────────────────────────────────────────────────────────────

def _clamp_position(x: float, y: float) -> tuple[float, float]:
    """Clamp (x, y) to workspace bounds to prevent out-of-range robot commands."""
    x = max(WORKSPACE_X_MIN, min(WORKSPACE_X_MAX, x))
    y = max(WORKSPACE_Y_MIN, min(WORKSPACE_Y_MAX, y))
    return (x, y)


def _find_in_scene(scene: dict, query: str) -> dict | None:
    """
    Find an object in the scene by label.

    Supports:
    - Exact match:       "red disc"   → matches "red disc"
    - Partial match:     "red block"  → matches "red block" in label
    - Colour-only:       "red"        → matches "red disc", "red block"
    - Slot reference:    "slot 2"     → matches first disc in slot 2
    - Tray reference:    "tray_0"     → matches tray object
    """
    if not query:
        return None

    query_lower = query.lower().strip()
    objects     = scene.get("objects", [])

    # 1. Exact match
    for obj in objects:
        label = (obj.get("label") or obj.get("name", "")).lower()
        if label == query_lower:
            return _normalise_obj(obj)

    # 2. Partial match — query inside label or label inside query
    for obj in objects:
        label = (obj.get("label") or obj.get("name", "")).lower()
        if query_lower in label or label in query_lower:
            return _normalise_obj(obj)

    # 3. Colour-only match — "red" matches "red disc"
    for obj in objects:
        colour = (obj.get("colour") or "").lower()
        if colour and colour == query_lower:
            return _normalise_obj(obj)

    # 4. Slot reference — "slot 2" finds first disc in slot 2
    if query_lower.startswith("slot"):
        parts = query_lower.split()
        if len(parts) >= 2 and parts[1].isdigit():
            slot_idx = int(parts[1])
            for obj in objects:
                if obj.get("slot") == slot_idx:
                    return _normalise_obj(obj)

    return None


def _normalise_obj(obj: dict) -> dict:
    """Normalise position to (x, y) float tuple."""
    pos = obj.get("position", (0.0, 0.0))
    if isinstance(pos, (list, tuple)):
        position = (float(pos[0]), float(pos[1]))
    elif isinstance(pos, dict):
        position = (float(pos.get("x", 0)), float(pos.get("y", 0)))
    else:
        position = (0.0, 0.0)
    return {
        "label":    obj.get("label") or obj.get("name"),
        "position": position,
        "colour":   obj.get("colour"),
        "shape":    obj.get("shape"),
        "slot":     obj.get("slot"),
        "tray":     obj.get("tray"),
    }


def _find_empty_slot(scene: dict, tray_label: str) -> tuple | None:
    """
    Find the first empty slot in a tray.
    A slot is empty if no disc in the scene has that slot index in that tray.
    """
    trays = scene.get("trays", [])
    tray  = next((t for t in trays if t.get("label") == tray_label), None)
    if not tray:
        return None

    occupied = {
        obj.get("slot")
        for obj in scene.get("objects", [])
        if obj.get("tray") == tray_label and obj.get("slot") is not None
    }

    for slot_idx, slot_pos in enumerate(tray.get("slots", [])):
        if slot_idx not in occupied:
            return (slot_idx, tuple(slot_pos))

    return None


def _apply_spatial_offset(
    ref_position: tuple[float, float],
    spatial_relation: str | None,
) -> tuple[float, float]:
    """Apply spatial offset and clamp to workspace bounds."""
    if not spatial_relation:
        return _clamp_position(*ref_position)

    relation_lower = spatial_relation.lower().strip()
    dx, dy = SPATIAL_OFFSETS.get(relation_lower, DEFAULT_OFFSET)
    x = ref_position[0] + dx
    y = ref_position[1] + dy
    clamped = _clamp_position(x, y)

    if clamped != (x, y):
        logger.warning(
            f"Position ({x:.3f}, {y:.3f}) clamped to workspace bounds → {clamped}"
        )

    return clamped


# ── Task planner ───────────────────────────────────────────────────────────────

class TaskPlanner:
    """
    Rule-based task planner.
    Supports: pick, place, move, locate, spatial relations,
              multi-step instructions, disc/slot operations.
    """

    def generate_plan(
        self,
        parsed: ParsedInstruction,
        scene: dict,
        task_id: str | None = None,
    ) -> ActionPlan:
        """
        Generate a step-by-step ActionPlan from a ParsedInstruction and scene.

        Raises:
            ValueError: If required objects are not found in the scene.
        """
        action = parsed.action.value
        logger.info(
            f"Planning: action={action}, object={parsed.object_target}, "
            f"destination={parsed.destination}, spatial={parsed.spatial_relation}"
        )

        # Disc-specific routing — object contains "disc" or colour matches a disc
        if self._is_disc_operation(parsed, scene):
            steps = self._plan_disc_pick(parsed, scene)

        elif (action == ActionType.PICK.value and
              parsed.destination and
              parsed.spatial_relation and
              parsed.spatial_relation.lower() not in ("in",)):
            steps = self._plan_pick_with_spatial(parsed, scene)

        elif action == ActionType.PICK.value:
            steps = self._plan_pick(parsed, scene)

        elif action == ActionType.PLACE.value:
            steps = self._plan_place(parsed, scene)

        elif action == ActionType.MOVE.value:
            steps = self._plan_move(parsed, scene)

        elif action == ActionType.LOCATE.value:
            steps = self._plan_locate(parsed, scene)

        else:
            raise ValueError(f"Unknown action type: {action}")

        return ActionPlan(
            task_id=task_id,
            instruction=parsed.raw_instruction,
            commands=steps,
        )

    def _is_disc_operation(self, parsed: ParsedInstruction, scene: dict) -> bool:
        """
        Check if this instruction involves a disc in a tray slot.
        True when the object is labelled as a disc or matched to a disc in scene.
        """
        obj_lower = (parsed.object_target or "").lower()

        # Explicit disc mention
        if "disc" in obj_lower:
            return True

        # Object resolves to a disc in the scene
        obj = _find_in_scene(scene, parsed.object_target or "")
        if obj and obj.get("shape") == "circle" and obj.get("slot") is not None:
            return True

        return False

    # ── Destination resolver ───────────────────────────────────────────────────

    def _resolve_destination(
        self,
        parsed: ParsedInstruction,
        scene: dict,
    ) -> tuple[str, Position]:
        """
        Resolve destination position with optional spatial offset.
        Returns (label, Position).
        """
        dest_name = parsed.destination or "right tray"
        dest      = _find_in_scene(scene, dest_name)

        if dest is None:
            raise ValueError(
                f"Destination '{dest_name}' not found in scene. "
                f"Available: {[o.get('label') for o in scene.get('objects', [])]}"
            )

        raw_pos = dest["position"]

        if parsed.spatial_relation:
            computed = _apply_spatial_offset(raw_pos, parsed.spatial_relation)
            logger.info(
                f"Spatial offset applied: '{parsed.spatial_relation}' "
                f"to {raw_pos} → {computed}"
            )
            pos   = Position(x=computed[0], y=computed[1])
            label = f"{dest_name} [{parsed.spatial_relation}]"
        else:
            pos   = Position(x=raw_pos[0], y=raw_pos[1])
            label = dest_name

        return label, pos

    # ── Disc/slot planning ─────────────────────────────────────────────────────

    def _plan_disc_pick(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        """
        Sprint 5 — Disc pick and place.

        Handles:
        - "pick up the red disc"
        - "pick up the red disc from slot 2"
        - "pick up the red disc and place it in slot 0 of tray_1"
        - "move the red disc to the right tray"
        """
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        # Find the disc in scene
        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(
                f"Disc '{obj_name}' not found in scene. "
                f"Available: {[o.get('label') for o in scene.get('objects', [])]}"
            )

        obj_pos = Position(x=obj["position"][0], y=obj["position"][1])
        slot    = obj.get("slot")
        tray    = obj.get("tray")

        # Step 1: Locate
        slot_info = f" in slot {slot} of {tray}" if slot is not None else ""
        steps.append(RobotCommand(
            step=step_n,
            command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}'{slot_info} at {obj['position']}",
        ))
        step_n += 1

        # Step 2: Move to disc
        steps.append(RobotCommand(
            step=step_n,
            command_type=CommandType.MOVE,
            target_object=obj_name,
            target_position=obj_pos,
            description=f"Navigate arm to '{obj_name}'",
        ))
        step_n += 1

        # Step 3: Pick
        steps.append(RobotCommand(
            step=step_n,
            command_type=CommandType.PICK,
            target_object=obj_name,
            description=f"Grasp '{obj_name}' from slot {slot}",
        ))
        step_n += 1

        # Step 4+: Place at destination if specified
        if parsed.destination:
            dest_label, dest_pos = self._resolve_disc_destination(
                parsed, scene
            )
            steps.append(RobotCommand(
                step=step_n,
                command_type=CommandType.MOVE,
                target_object=parsed.destination,
                target_position=dest_pos,
                description=f"Navigate to '{dest_label}'",
            ))
            step_n += 1
            steps.append(RobotCommand(
                step=step_n,
                command_type=CommandType.PLACE,
                target_object=parsed.destination,
                description=f"Place '{obj_name}' at '{dest_label}'",
            ))

        return steps

    def _resolve_disc_destination(
        self,
        parsed: ParsedInstruction,
        scene: dict,
    ) -> tuple[str, Position]:
        """
        Resolve destination for a disc — supports:
        - Named tray: "left tray", "tray_0"
        - Specific slot: "slot 2", "slot 2 in tray_1"
        - Empty slot (auto): finds first empty slot in destination tray
        """
        dest_name = parsed.destination or ""
        dest_lower = dest_name.lower()

        # Slot reference — "slot 2"
        if dest_lower.startswith("slot"):
            parts = dest_lower.split()
            if len(parts) >= 2 and parts[1].isdigit():
                slot_idx = int(parts[1])
                trays    = scene.get("trays", [])
                for tray in trays:
                    slots = tray.get("slots", [])
                    if slot_idx < len(slots):
                        sx, sy = slots[slot_idx]
                        return (
                            f"slot {slot_idx} of {tray['label']}",
                            Position(x=float(sx), y=float(sy))
                        )

        # Named tray — find first empty slot
        dest_obj = _find_in_scene(scene, dest_name)
        if dest_obj:
            # Try to find an empty slot in this tray
            tray_label = dest_name if "tray" in dest_name.lower() else None
            if tray_label:
                empty = _find_empty_slot(scene, tray_label)
                if empty:
                    slot_idx, (sx, sy) = empty
                    logger.info(
                        f"Auto-assigned empty slot {slot_idx} in {tray_label} "
                        f"at ({sx}, {sy})"
                    )
                    return (
                        f"slot {slot_idx} of {tray_label}",
                        Position(x=float(sx), y=float(sy))
                    )

            # Fall back to tray center
            pos = dest_obj["position"]
            return dest_name, Position(x=pos[0], y=pos[1])

        # Last resort — use spatial offset resolver
        return self._resolve_destination(parsed, scene)

    # ── Standard planning methods ──────────────────────────────────────────────

    def _plan_pick(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        """Pick only, or pick + place at named destination."""
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(
                f"Object '{obj_name}' not found in scene. "
                f"Available: {[o.get('label') for o in scene.get('objects', [])]}"
            )

        obj_pos = Position(x=obj["position"][0], y=obj["position"][1])

        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}' in scene at {obj['position']}",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.MOVE,
            target_object=obj_name, target_position=obj_pos,
            description=f"Navigate arm to '{obj_name}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PICK,
            target_object=obj_name,
            description=f"Grasp '{obj_name}'",
        ))
        step_n += 1

        if parsed.destination:
            dest_label, dest_pos = self._resolve_destination(parsed, scene)
            steps.append(RobotCommand(
                step=step_n, command_type=CommandType.MOVE,
                target_object=parsed.destination, target_position=dest_pos,
                description=f"Navigate to '{dest_label}'",
            ))
            step_n += 1
            steps.append(RobotCommand(
                step=step_n, command_type=CommandType.PLACE,
                target_object=parsed.destination,
                description=f"Place '{obj_name}' at '{dest_label}'",
            ))

        return steps

    def _plan_pick_with_spatial(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        """Pick + place with spatial offset destination."""
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")

        obj_pos            = Position(x=obj["position"][0], y=obj["position"][1])
        dest_label, dest_pos = self._resolve_destination(parsed, scene)

        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}' at {obj['position']}",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.MOVE,
            target_object=obj_name, target_position=obj_pos,
            description=f"Navigate to '{obj_name}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PICK,
            target_object=obj_name,
            description=f"Grasp '{obj_name}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.MOVE,
            target_object=parsed.destination, target_position=dest_pos,
            description=f"Navigate to {dest_label} ({dest_pos.x:.3f}, {dest_pos.y:.3f})",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PLACE,
            target_object=parsed.destination,
            description=f"Place '{obj_name}' {parsed.spatial_relation} '{parsed.destination}'",
        ))

        return steps

    def _plan_place(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        """Locate → move → pick → move to destination → place."""
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")

        obj_pos              = Position(x=obj["position"][0], y=obj["position"][1])
        dest_label, dest_pos = self._resolve_destination(parsed, scene)

        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}' exists at {obj['position']}",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.MOVE,
            target_object=obj_name, target_position=obj_pos,
            description=f"Navigate to '{obj_name}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PICK,
            target_object=obj_name,
            description=f"Grasp '{obj_name}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.MOVE,
            target_object=parsed.destination or "destination",
            target_position=dest_pos,
            description=f"Navigate to '{dest_label}'",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PLACE,
            target_object=parsed.destination or "destination",
            description=f"Release '{obj_name}' at '{dest_label}'",
        ))

        return steps

    def _plan_move(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        return self._plan_place(parsed, scene)

    def _plan_locate(
        self, parsed: ParsedInstruction, scene: dict
    ) -> list[RobotCommand]:
        obj_name = parsed.object_target
        obj      = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")
        return [RobotCommand(
            step=1,
            command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Find '{obj_name}' at {obj['position']}",
        )]

    # ── Multi-step ─────────────────────────────────────────────────────────────

    def plan_multi_step(
        self,
        instructions: list[ParsedInstruction],
        scene: dict,
        task_id: str | None = None,
    ) -> ActionPlan:
        """
        Generate a compound plan for multiple sequential instructions.
        Commands are renumbered sequentially across all sub-plans.
        """
        all_commands = []
        step_offset  = 0

        for i, parsed in enumerate(instructions):
            sub_plan = self.generate_plan(parsed, scene, task_id=None)
            for cmd in sub_plan.commands:
                all_commands.append(
                    cmd.model_copy(update={"step": cmd.step + step_offset})
                )
            step_offset += len(sub_plan.commands)
            logger.info(f"Sub-plan {i+1}: {len(sub_plan.commands)} steps added")

        return ActionPlan(
            task_id=task_id,
            instruction=" | ".join(p.raw_instruction for p in instructions),
            commands=all_commands,
        )