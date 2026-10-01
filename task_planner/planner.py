"""
task_planner/planner.py
-----------------------
Rule-based task planner. Combines a ParsedInstruction and the current scene
into an ordered ActionPlan of RobotCommands.

Capabilities:
    - Single-action planning: locate → move → pick → move → place, for plain
      pick/place/move/locate instructions.
    - Spatial relation handling: "left of", "right of", "near", "on top of",
      "next to", "in front of", "behind" → calculates an offset position
      relative to a reference object (see TECHNICAL_NOTES.md for the offset
      table and axis convention).
    - Disc and tray slot support (Sprint 5, DISC-1): "pick up the red disc
      from slot 2", colour-only matching ("red" → "red disc"), slot lookup
      ("slot 0"), and auto-assignment of the first empty slot in a tray.
    - Multi-action planning (plan_multi_step()): chains several parsed
      actions into one continuous, sequentially renumbered ActionPlan.
      Plans each action against a working copy of the scene that is updated
      after every sub-plan, and tracks gripper state across actions so a
      pick with no matching place is caught at plan time rather than failing
      mid-execution.

Usage:
    from task_planner.planner import TaskPlanner
    planner = TaskPlanner()
    plan    = planner.generate_plan(parsed_instruction, scene)
    plan.print_plan()

    # Multi-action:
    plan = planner.plan_multi_step(parsed_instructions, scene)
"""

import copy
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm_backend.schema import ParsedInstruction, ActionType
from simulation_backend.action_schema import ActionPlan, RobotCommand, CommandType, Position

logger = logging.getLogger(__name__)

# ── Spatial offset map ─────────────────────────────────────────────────────────
# Maps spatial relation strings to (dx, dy) offsets in METRES, matching the units
# used throughout scene_config.yaml. Applied relative to the reference object's
# position.
#
# Axis convention is the workspace's own: +X points away from the robot base,
# +Y is the robot's left. That is why 'left tray' sits at y=+0.45 and
# 'right tray' at y=-0.45 — so left/right offsets move along Y, and
# front/behind along X.
_CLEARANCE_M = 0.15   # gap from the reference object's centre; blocks are 0.05 m

SPATIAL_OFFSETS: dict[str, tuple[float, float]] = {
    "left of":    ( 0.0,  _CLEARANCE_M),
    "left":       ( 0.0,  _CLEARANCE_M),
    "right of":   ( 0.0, -_CLEARANCE_M),
    "right":      ( 0.0, -_CLEARANCE_M),
    "near":       (-0.10,  0.10),
    "next to":    ( 0.0,  _CLEARANCE_M),
    "on top of":  ( 0.0,  0.0),   # same x,y; height handled by real sim
    "in front of":(-_CLEARANCE_M, 0.0),   # between the robot base and the object
    "behind":     ( _CLEARANCE_M, 0.0),
    "in":         ( 0.0,  0.0),   # inside container → use container position
    # S5-3: "move X to the left tray" parses as spatial_relation="to". Without
    # these, "to"/"into"/"onto" fell through to DEFAULT_OFFSET and the drop-off
    # landed off the container centre.
    "to":         ( 0.0,  0.0),
    "into":       ( 0.0,  0.0),
    "onto":       ( 0.0,  0.0),
    "inside":     ( 0.0,  0.0),
    "at":         ( 0.0,  0.0),
    # Sprint 5 (disc work): no vertical offset in the 2D plan
    "above":      ( 0.0,  0.0),
    "below":      ( 0.0,  0.0),
}

DEFAULT_OFFSET = (0.0, _CLEARANCE_M)  # fallback when relation not in map

# ── Workspace bounds (metres) ─────────────────────────────────────────────────
# Available through _clamp_position(); not applied automatically yet
WORKSPACE_X_MIN = 0.15
WORKSPACE_X_MAX = 0.75
WORKSPACE_Y_MIN = -0.45
WORKSPACE_Y_MAX =  0.45

# How close (metres) a drop-off position must be to a slot to count as "in" it
SLOT_TOLERANCE_M = 0.005


# ── Scene helpers ──────────────────────────────────────────────────────────────

def _clamp_position(x: float, y: float) -> tuple[float, float]:
    """Clamp (x, y) to workspace bounds to prevent out-of-range robot commands."""
    x = max(WORKSPACE_X_MIN, min(WORKSPACE_X_MAX, x))
    y = max(WORKSPACE_Y_MIN, min(WORKSPACE_Y_MAX, y))
    return (x, y)


def _normalise_obj(obj: dict) -> dict:
    """Normalise position to (x, y) float tuple and keep the disc fields."""
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


def _find_in_scene(scene: dict, query: str) -> dict | None:
    """
    Find an object in the scene by label.

    Supports (checked in this order):
    - Exact match:       "red disc"   → matches "red disc"
    - Partial match:     "red block"  → query inside label, or label inside query
    - Colour-only:       "red"        → matches an object whose colour is "red"
    - Slot reference:    "slot 2"     → matches first disc in slot 2
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

    # 2. Partial match
    for obj in objects:
        label = (obj.get("label") or obj.get("name", "")).lower()
        if query_lower in label or label in query_lower:
            return _normalise_obj(obj)

    # 3. Colour-only match
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


def _find_empty_slot(scene: dict, tray_label: str) -> tuple | None:
    """
    Find the first empty slot in a tray.
    A slot is empty if no disc in the scene has that slot index in that tray.
    Returns (slot_index, (x, y)) or None.
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


def _slot_at(scene: dict, x: float, y: float) -> tuple[int | None, str | None]:
    """
    Return (slot_index, tray_label) if (x, y) is on one of the tray slots,
    otherwise (None, None). Used to keep disc occupancy right in the working
    scene during multi-step planning.
    """
    for tray in scene.get("trays", []):
        for slot_idx, slot_pos in enumerate(tray.get("slots", [])):
            if (abs(float(slot_pos[0]) - x) <= SLOT_TOLERANCE_M and
                    abs(float(slot_pos[1]) - y) <= SLOT_TOLERANCE_M):
                return (slot_idx, tray.get("label"))
    return (None, None)


def _apply_spatial_offset(
    ref_position: tuple[float, float],
    spatial_relation: str | None,
) -> tuple[float, float]:
    """
    Calculate a target position by applying a spatial offset to a reference position.

    Args:
        ref_position:     (x, y) of the reference object
        spatial_relation: string like "left of", "near", "right of"

    Returns:
        (x, y) of the computed target position
    """
    if not spatial_relation:
        return ref_position

    relation_lower = spatial_relation.lower().strip()
    dx, dy = SPATIAL_OFFSETS.get(relation_lower, DEFAULT_OFFSET)
    return (ref_position[0] + dx, ref_position[1] + dy)


# ── Task planner ───────────────────────────────────────────────────────────────

class TaskPlanner:
    """
    Rule-based task planner — Sprint 2 + Sprint 3 + Sprint 5.

    Sprint 3 additions:
    - _resolve_destination(): uses spatial_relation to compute offset positions
    - plan_multi_step(): handles compound multi-action instructions
    - generate_plan(): detects multi-step and routes accordingly

    Sprint 5 additions:
    - _is_disc_operation() / _plan_disc_pick(): disc and tray slot support
    - _resolve_disc_destination(): named slot, or first empty slot in a tray
    """

    def generate_plan(
        self,
        parsed: ParsedInstruction,
        scene: dict,
        task_id: str | None = None,
    ) -> ActionPlan:
        """
        Generate a step-by-step ActionPlan from instruction and scene.

        Handles:
        - Disc / slot instructions ("pick up the red disc from slot 2")
        - Simple single-action instructions (pick, place, move, locate)
        - Spatial relation instructions ("left of", "near", "right of" etc.)
        - Multi-step instructions ("pick A then move B")

        Raises:
            ValueError: If required objects are not found in the scene
        """
        action = parsed.action.value
        logger.info(f"Planning: action={action}, object={parsed.object_target}, "
                    f"destination={parsed.destination}, spatial={parsed.spatial_relation}")

        # Disc-specific routing — object contains "disc" or resolves to a disc
        if self._is_disc_operation(parsed, scene):
            steps = self._plan_disc_pick(parsed, scene)

        # Detect multi-step: action=pick AND destination present AND spatial_relation
        # indicates a compound instruction (pick A and place it relative to B)
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
        True when the object is labelled as a disc or matches a disc in the scene.
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
        Resolve the destination position, applying spatial offset if present.

        Returns:
            (destination_label, Position) — the label and computed position
        """
        dest_name = parsed.destination or "right tray"
        dest = _find_in_scene(scene, dest_name)

        if dest is None:
            raise ValueError(
                f"Destination '{dest_name}' not found in scene. "
                f"Available: {[o.get('label') for o in scene.get('objects', [])]}"
            )

        raw_pos = dest["position"]

        if parsed.spatial_relation:
            computed = _apply_spatial_offset(raw_pos, parsed.spatial_relation)
            logger.info(f"Spatial offset applied: '{parsed.spatial_relation}' "
                        f"to {raw_pos} → {computed}")
            pos = Position(x=computed[0], y=computed[1])
            label = f"{dest_name} [{parsed.spatial_relation}]"
        else:
            pos   = Position(x=raw_pos[0], y=raw_pos[1])
            label = dest_name

        return label, pos

    # ── Disc / slot planning (Sprint 5) ────────────────────────────────────────

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

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(
                f"Disc '{obj_name}' not found in scene. "
                f"Available: {[o.get('label') for o in scene.get('objects', [])]}"
            )

        obj_pos = Position(x=obj["position"][0], y=obj["position"][1])
        slot    = obj.get("slot")
        tray    = obj.get("tray")
        slot_info = f" in slot {slot} of {tray}" if slot is not None else ""

        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}'{slot_info} at {obj['position']}",
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
            description=f"Grasp '{obj_name}'{slot_info}",
        ))
        step_n += 1

        if parsed.destination:
            dest_label, dest_pos = self._resolve_disc_destination(parsed, scene)
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

    def _resolve_disc_destination(
        self,
        parsed: ParsedInstruction,
        scene: dict,
    ) -> tuple[str, Position]:
        """
        Resolve destination for a disc — supports:
        - Specific slot: "slot 2"
        - Named tray: "left tray" → first empty slot in that tray
        - Anything else falls back to the normal spatial resolver
        """
        dest_name  = parsed.destination or ""
        dest_lower = dest_name.lower()

        # Slot reference — "slot 2"
        if dest_lower.startswith("slot"):
            parts = dest_lower.split()
            if len(parts) >= 2 and parts[1].isdigit():
                slot_idx = int(parts[1])
                for tray in scene.get("trays", []):
                    slots = tray.get("slots", [])
                    if slot_idx < len(slots):
                        sx, sy = slots[slot_idx]
                        return (
                            f"slot {slot_idx} of {tray['label']}",
                            Position(x=float(sx), y=float(sy)),
                        )

        # Named tray — find first empty slot
        dest_obj = _find_in_scene(scene, dest_name)
        if dest_obj:
            if "tray" in dest_lower:
                empty = _find_empty_slot(scene, dest_name)
                if empty:
                    slot_idx, (sx, sy) = empty
                    logger.info(
                        f"Auto-assigned empty slot {slot_idx} in {dest_name} "
                        f"at ({sx}, {sy})"
                    )
                    return (
                        f"slot {slot_idx} of {dest_name}",
                        Position(x=float(sx), y=float(sy)),
                    )

            # Fall back to tray centre
            pos = dest_obj["position"]
            return dest_name, Position(x=pos[0], y=pos[1])

        # Last resort — use the spatial offset resolver
        return self._resolve_destination(parsed, scene)

    # ── Standard planning methods ──────────────────────────────────────────────

    def _plan_pick(self, parsed: ParsedInstruction, scene: dict) -> list[RobotCommand]:
        """Pick only, or pick + place at named destination (no spatial offset)."""
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
        """
        PB7-SP: Pick + place with spatial offset destination.
        e.g. "place the red block to the left of the blue block"
        → moves to blue block position − spatial offset, not to a named tray.
        """
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")

        obj_pos = Position(x=obj["position"][0], y=obj["position"][1])

        # Resolve offset destination
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
            description=f"Navigate to computed position {dest_label} "
                        f"({dest_pos.x:.3f}, {dest_pos.y:.3f})",
        ))
        step_n += 1
        steps.append(RobotCommand(
            step=step_n, command_type=CommandType.PLACE,
            target_object=parsed.destination,
            description=f"Place '{obj_name}' {parsed.spatial_relation} '{parsed.destination}'",
        ))

        return steps

    def _plan_place(self, parsed: ParsedInstruction, scene: dict) -> list[RobotCommand]:
        """Locate → move → pick → move to destination (with optional spatial offset) → place."""
        steps    = []
        step_n   = 1
        obj_name = parsed.object_target

        obj = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")

        obj_pos            = Position(x=obj["position"][0], y=obj["position"][1])
        dest_label, dest_pos = self._resolve_destination(parsed, scene)

        steps.append(RobotCommand(step=step_n, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Confirm '{obj_name}' exists at {obj['position']}"))
        step_n += 1
        steps.append(RobotCommand(step=step_n, command_type=CommandType.MOVE,
            target_object=obj_name, target_position=obj_pos,
            description=f"Navigate to '{obj_name}'"))
        step_n += 1
        steps.append(RobotCommand(step=step_n, command_type=CommandType.PICK,
            target_object=obj_name,
            description=f"Grasp '{obj_name}'"))
        step_n += 1
        steps.append(RobotCommand(step=step_n, command_type=CommandType.MOVE,
            target_object=parsed.destination or "destination", target_position=dest_pos,
            description=f"Navigate to '{dest_label}'"))
        step_n += 1
        steps.append(RobotCommand(step=step_n, command_type=CommandType.PLACE,
            target_object=parsed.destination or "destination",
            description=f"Release '{obj_name}' at '{dest_label}'"))

        return steps

    def _plan_move(self, parsed: ParsedInstruction, scene: dict) -> list[RobotCommand]:
        return self._plan_place(parsed, scene)

    def _plan_locate(self, parsed: ParsedInstruction, scene: dict) -> list[RobotCommand]:
        obj_name = parsed.object_target
        obj      = _find_in_scene(scene, obj_name)
        if obj is None:
            raise ValueError(f"Object '{obj_name}' not found in scene")
        return [RobotCommand(
            step=1, command_type=CommandType.LOCATE,
            target_object=obj_name,
            description=f"Find '{obj_name}' at {obj['position']}",
        )]

    def plan_multi_step(
        self,
        instructions: list[ParsedInstruction],
        scene: dict,
        task_id: str | None = None,
    ) -> ActionPlan:
        """
        PB7-MULTI: Generate a compound plan for multiple sequential instructions.

        Each instruction produces its own sub-plan. Commands are renumbered
        sequentially so the executor runs them as a single continuous plan.

        Args:
            instructions: List of ParsedInstruction objects (in order)
            scene:        Scene dict — shared across all sub-plans
            task_id:      Optional tracker task_id

        Returns:
            Single ActionPlan with all steps from all sub-plans combined

        Example:
            instructions = [
                ParsedInstruction(action=pick, object="red block", ...),
                ParsedInstruction(action=pick, object="blue block", destination="right tray", ...),
            ]
        """
        all_commands = []
        step_offset  = 0

        # S5-3: plan each action against a WORKING COPY of the scene that is
        # updated after every sub-plan. Without this, action 2 would still be
        # planned against action 1's starting positions, so an instruction like
        # "move the red block to the left tray then move it to the right tray"
        # would target a block that is no longer there.
        working_scene = copy.deepcopy(scene)

        # S5-3: the robot has ONE gripper. If an action picks something up and
        # never puts it down, the next action cannot pick anything else. Catch
        # that here, at plan time, with a clear reason — instead of letting the
        # executor fail halfway through a partially executed plan.
        held_object: str | None = None
        held_by_action: int = 0

        for i, parsed in enumerate(instructions):
            try:
                sub_plan = self.generate_plan(parsed, working_scene, task_id=None)
            except ValueError as e:
                # Fail safely with a clear reason naming the offending action,
                # instead of silently dropping it or executing a partial plan.
                raise ValueError(
                    f"Action {i + 1}/{len(instructions)} "
                    f"('{parsed.raw_instruction}') could not be planned: {e}"
                ) from e

            picks  = sum(1 for c in sub_plan.commands
                         if c.command_type == CommandType.PICK)
            places = sum(1 for c in sub_plan.commands
                         if c.command_type == CommandType.PLACE)

            if held_object and picks:
                raise ValueError(
                    f"Action {i + 1}/{len(instructions)} "
                    f"('{parsed.raw_instruction}') needs the gripper, but the "
                    f"robot is still holding '{held_object}' from action "
                    f"{held_by_action}. Give action {held_by_action} a "
                    f"destination, or place '{held_object}' before this action."
                )

            for cmd in sub_plan.commands:
                new_cmd = cmd.model_copy(
                    update={"step": cmd.step + step_offset}
                )
                all_commands.append(new_cmd)
            step_offset += len(sub_plan.commands)

            if picks > places:
                held_object    = parsed.object_target
                held_by_action = i + 1
            elif places:
                held_object    = None
                held_by_action = 0

            self._apply_plan_to_scene(working_scene, parsed, sub_plan)
            logger.info(f"Sub-plan {i+1}: {len(sub_plan.commands)} steps added")

        combined_instruction = " | ".join(p.raw_instruction for p in instructions)

        return ActionPlan(
            task_id=task_id,
            instruction=combined_instruction,
            commands=all_commands,
        )

    # -- Predicted scene state (S5-3) -------------------------------------------

    @staticmethod
    def _apply_plan_to_scene(scene: dict, parsed: ParsedInstruction, sub_plan) -> None:
        """
        Update a working scene dict to reflect where a sub-plan leaves its object.

        Called between sub-plans in plan_multi_step() so later actions are
        planned against the predicted workspace state rather than the original
        one. Only moves that actually end in a PLACE change anything; LOCATE and
        bare PICK leave the scene untouched.

        Sprint 5: if the object lands on a tray slot, its slot/tray fields are
        updated too, so the next disc is not assigned the same slot.

        Args:
            scene:    Working scene dict — mutated in place.
            parsed:   The instruction this sub-plan came from.
            sub_plan: The ActionPlan generated for it.
        """
        from simulation_backend.action_schema import CommandType

        if not any(c.command_type == CommandType.PLACE for c in sub_plan.commands):
            return

        # The final MOVE before the PLACE carries the drop-off position.
        final_position = None
        for cmd in sub_plan.commands:
            if cmd.command_type == CommandType.MOVE and cmd.target_position is not None:
                final_position = cmd.target_position
        if final_position is None:
            return

        query = (parsed.object_target or "").lower()
        for obj in scene.get("objects", []):
            label = (obj.get("label") or obj.get("name") or "").lower()
            if query and (query in label or label in query):
                obj["position"] = (final_position.x, final_position.y)

                # Keep slot occupancy in sync for discs
                slot_idx, tray_label = _slot_at(scene, final_position.x, final_position.y)
                if slot_idx is not None or obj.get("slot") is not None:
                    obj["slot"] = slot_idx
                    obj["tray"] = tray_label

                logger.info(
                    f"Predicted scene update: '{label}' -> "
                    f"({final_position.x:.2f}, {final_position.y:.2f})"
                )
                return
