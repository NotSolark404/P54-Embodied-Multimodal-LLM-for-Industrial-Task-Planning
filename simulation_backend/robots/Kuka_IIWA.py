"""
simulation_backend/robots/Kuka_IIWA.py
--------------------------------------
Minimum PyBullet KUKA IIWA controller for the pipeline executor.

The KUKA model bundled with pybullet_data has a 7-DOF arm and no gripper.
For SIM-FINAL pick/place evidence we use the same Executor-facing interface as
MockRobot and FrankaPanda, and represent grasping with a fixed PyBullet
constraint between the KUKA end-effector link and the selected object.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

import pybullet as p

from simulation_backend.mock_robot import CommandResult
from simulation_backend.robots.robot_base import RobotBase
from simulation_backend.simulation_environment.object_registry import ObjectRegistry

logger = logging.getLogger(__name__)


class KukaIIWA(RobotBase):
    """KUKA IIWA 7-DOF arm with constraint-based pick and place."""

    model_name = "kuka_iiwa"

    _NUM_ARM_JOINTS = 7
    _EE_LINK = 6
    _HOME_JOINTS = [0.0, 0.4, 0.0, -1.6, 0.0, 1.2, 0.0]
    _IK_DAMPING = [0.08] * 7

    def __init__(
        self,
        physics_client: int,
        body_id: int,
        registry: ObjectRegistry,
        config: dict = None,
    ) -> None:
        super().__init__(physics_client, body_id, config)
        self._registry = registry
        self._constraint_id: Optional[int] = None

        self._move_steps = int(float(os.getenv("KUKA_MOVE_STEPS", str(self._cfg.get("move_steps", 900)))))
        self._pos_tol = float(os.getenv("KUKA_POS_TOL", str(self._cfg.get("position_tol", 0.035))))
        self._arm_force = float(os.getenv("KUKA_ARM_FORCE", str(self._cfg.get("arm_force", 240.0))))
        self._max_vel = float(os.getenv("KUKA_MAX_VEL", str(self._cfg.get("max_velocity", 2.5))))
        self._transit_z = float(os.getenv("KUKA_TRANSIT_Z", str(self._cfg.get("transit_z", 0.42))))
        self._step_sleep = float(os.getenv("KUKA_STEP_SLEEP", str(self._cfg.get("step_sleep", 0.001))))

        self._APPROACH_HEIGHT = float(self._cfg.get("approach_height", 0.16))
        self._GRASP_HEIGHT = float(self._cfg.get("grasp_height", 0.035))
        self._PLACE_HEIGHT = float(self._cfg.get("place_height", 0.08))
        self._RETRACT_HEIGHT = float(self._cfg.get("retract_height", 0.24))

        logger.info(
            "[kuka_iiwa] Initialised — body_id=%s move_steps=%s pos_tol=%.3fm",
            body_id,
            self._move_steps,
            self._pos_tol,
        )

    def reset(self) -> None:
        """Reset arm joints and clear any held-object constraint."""
        self._remove_constraint()

        for joint_idx, pos in enumerate(self._HOME_JOINTS):
            p.resetJointState(
                self._body_id,
                joint_idx,
                pos,
                physicsClientId=self._client,
            )

        self._held_object = None
        self._position = self._read_tcp_position()
        logger.info("[kuka_iiwa] Reset to home pose.")

    def move_to(self, x: float, y: float, z: float = 0.0) -> CommandResult:
        """Move KUKA TCP to absolute world coordinates via IK."""
        start = time.perf_counter()

        if not self._within_bounds(x, y, z):
            return CommandResult(
                success=False,
                command="move_to",
                message=f"Target ({x:.3f}, {y:.3f}, {z:.3f}) outside workspace bounds.",
                latency_ms=self._elapsed(start),
            )

        target = [float(x), float(y), float(z)]
        joint_angles = p.calculateInverseKinematics(
            self._body_id,
            self._EE_LINK,
            targetPosition=target,
            jointDamping=self._IK_DAMPING,
            physicsClientId=self._client,
        )

        for joint_idx in range(self._NUM_ARM_JOINTS):
            p.setJointMotorControl2(
                bodyIndex=self._body_id,
                jointIndex=joint_idx,
                controlMode=p.POSITION_CONTROL,
                targetPosition=joint_angles[joint_idx],
                force=self._arm_force,
                maxVelocity=self._max_vel,
                physicsClientId=self._client,
            )

        reached = self._step_to_target(target, self._move_steps)
        tcp = self._read_tcp_position()
        self._position = tcp

        message = (
            f"Moved to ({x:.3f}, {y:.3f}, {z:.3f}) — "
            f"TCP=({tcp[0]:.3f}, {tcp[1]:.3f}, {tcp[2]:.3f})"
            if reached
            else
            f"TCP did not converge to ({x:.3f}, {y:.3f}, {z:.3f}); "
            f"final TCP=({tcp[0]:.3f}, {tcp[1]:.3f}, {tcp[2]:.3f})"
        )

        result = CommandResult(
            success=reached,
            command="move_to",
            message=message,
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(result)
        return result

    def move_to_object(self, object_name: str) -> CommandResult:
        """Move to a safe approach height above a named scene object."""
        start = time.perf_counter()
        obj = self._find_object(object_name)

        if obj is None:
            return CommandResult(
                success=False,
                command="move_to_object",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        x, y, z = obj["position"]
        approach_z = z + self._APPROACH_HEIGHT
        result = self._move_via_transit(x, y, approach_z)
        result.command = "move_to_object"
        result.message = (
            f"Moved above '{object_name}' at ({x:.3f}, {y:.3f}, {approach_z:.3f})"
            if result.success
            else f"Failed to move above '{object_name}': {result.message}"
        )
        result.latency_ms = self._elapsed(start)
        self._log(result)
        return result

    def pick(self, object_name: str) -> CommandResult:
        """Approach, descend, attach the object to the end-effector, and lift."""
        start = time.perf_counter()

        if self._held_object is not None:
            return CommandResult(
                success=False,
                command="pick",
                message=f"Already holding '{self._held_object}'. Place it first.",
                latency_ms=self._elapsed(start),
            )

        obj = self._find_object(object_name)
        if obj is None:
            return CommandResult(
                success=False,
                command="pick",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        entry = self._registry.get_by_label(object_name)
        if entry is not None and not entry.graspable:
            return CommandResult(
                success=False,
                command="pick",
                message=f"Object '{object_name}' is not graspable.",
                latency_ms=self._elapsed(start),
            )

        x, y, z = obj["position"]

        result = self._move_via_transit(x, y, z + self._APPROACH_HEIGHT)
        if not result.success:
            return self._failed("pick", start, f"Approach failed for '{object_name}': {result.message}")

        result = self.move_to(x, y, z + self._GRASP_HEIGHT)
        if not result.success:
            return self._failed("pick", start, f"Descent failed for '{object_name}': {result.message}")

        body_id = self._get_object_body_id(object_name)
        if body_id is None:
            return self._failed("pick", start, f"Object body_id for '{object_name}' not found.")

        self._constraint_id = p.createConstraint(
            parentBodyUniqueId=self._body_id,
            parentLinkIndex=self._EE_LINK,
            childBodyUniqueId=body_id,
            childLinkIndex=-1,
            jointType=p.JOINT_FIXED,
            jointAxis=[0, 0, 0],
            parentFramePosition=[0.0, 0.0, 0.0],
            childFramePosition=[0.0, 0.0, 0.0],
            physicsClientId=self._client,
        )

        obj["held"] = True
        self._held_object = object_name

        result = self.move_to(x, y, self._transit_z)
        if not result.success:
            return self._failed("pick", start, f"Lift failed for '{object_name}': {result.message}")

        final = CommandResult(
            success=True,
            command="pick",
            message=f"Picked '{object_name}' with fixed EE constraint.",
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(final)
        return final

    def place(self, location_name: str) -> CommandResult:
        """Move above a destination, release the held object, settle, and retract."""
        start = time.perf_counter()

        if self._held_object is None:
            return CommandResult(
                success=False,
                command="place",
                message="Not holding any object.",
                latency_ms=self._elapsed(start),
            )

        dest = self._find_object(location_name)
        if dest is None:
            return CommandResult(
                success=False,
                command="place",
                message=f"Destination '{location_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        dx, dy, dz = dest["position"]
        placed_object = self._held_object

        result = self._move_via_transit(dx, dy, dz + self._APPROACH_HEIGHT)
        if not result.success:
            return self._failed("place", start, f"Transit to '{location_name}' failed: {result.message}")

        result = self.move_to(dx, dy, dz + self._PLACE_HEIGHT)
        if not result.success:
            return self._failed("place", start, f"Descent to '{location_name}' failed: {result.message}")

        self._remove_constraint()
        for _ in range(90):
            p.stepSimulation(physicsClientId=self._client)
            if self._step_sleep > 0:
                time.sleep(self._step_sleep)

        self._held_object = None
        held_key = placed_object.lower()
        if held_key in self._object_map:
            self._object_map[held_key]["position"] = (dx, dy, dz)
            self._object_map[held_key]["held"] = False

        self.move_to(dx, dy, dz + self._RETRACT_HEIGHT)

        final = CommandResult(
            success=True,
            command="place",
            message=f"Placed '{placed_object}' at '{location_name}' ({dx:.3f}, {dy:.3f}, {dz:.3f}).",
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(final)
        return final

    def locate(self, object_name: str) -> CommandResult:
        """Confirm object exists in the loaded planner scene."""
        start = time.perf_counter()
        obj = self._find_object(object_name)
        if obj is None:
            return CommandResult(
                success=False,
                command="locate",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        result = CommandResult(
            success=True,
            command="locate",
            message=f"Found '{object_name}' at {obj['position']}",
            latency_ms=self._elapsed(start),
            state={"position": obj["position"]},
        )
        self._log(result)
        return result

    def _move_via_transit(self, dest_x: float, dest_y: float, dest_z: float) -> CommandResult:
        """Move through safe waypoints: lift, swing, descend."""
        cur_x, cur_y, cur_z = self._position

        if cur_z < self._transit_z - 0.02:
            result = self.move_to(cur_x, cur_y, self._transit_z)
            if not result.success:
                result.message = f"[transit] Lift failed: {result.message}"
                return result

        result = self.move_to(dest_x, dest_y, self._transit_z)
        if not result.success:
            result.message = f"[transit] Swing failed: {result.message}"
            return result

        result = self.move_to(dest_x, dest_y, dest_z)
        if not result.success:
            result.message = f"[transit] Descent failed: {result.message}"
        return result

    def _read_tcp_position(self) -> tuple[float, float, float]:
        state = p.getLinkState(self._body_id, self._EE_LINK, physicsClientId=self._client)
        pos = state[0]
        return (round(pos[0], 5), round(pos[1], 5), round(pos[2], 5))

    def _step_to_target(self, target: list[float], max_steps: int) -> bool:
        tx, ty, tz = target
        for _ in range(max_steps):
            p.stepSimulation(physicsClientId=self._client)
            if self._step_sleep > 0:
                time.sleep(self._step_sleep)
            tcp = self._read_tcp_position()
            dist = ((tcp[0] - tx) ** 2 + (tcp[1] - ty) ** 2 + (tcp[2] - tz) ** 2) ** 0.5
            if dist < self._pos_tol:
                return True
        return False

    def _workspace_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """
        The box the TCP is allowed inside, from the shared project limits.

        This used to be the hardcoded pair ((0.05, -0.85, 0.0), (0.95, 0.85,
        0.75)). Those numbers allowed |y| up to 0.85 m on a table that is 1.5 m
        deep and therefore ends at y = +/-0.75, so the arm was permitted to reach
        0.10 m past the table edge and into a perimeter wall. They also did not
        match MockRobot's or Franka's. The limits now come from
        scene_config.yaml through task_planner.safety, so the table geometry and
        the reach limit cannot drift apart again.
        """
        return self._safety_limits().as_bounds()

    def _get_object_body_id(self, object_name: str) -> Optional[int]:
        entry = self._registry.get_by_label(object_name)
        if entry is not None:
            return entry.body_id
        name_lower = object_name.lower()
        for entry in self._registry.all_entries():
            label_lower = entry.label.lower()
            if name_lower in label_lower or label_lower in name_lower:
                return entry.body_id
        return None

    def _remove_constraint(self) -> None:
        if self._constraint_id is None:
            return
        try:
            p.removeConstraint(self._constraint_id, physicsClientId=self._client)
        except Exception as exc:
            logger.warning("[kuka_iiwa] Could not remove constraint: %s", exc)
        self._constraint_id = None

    def _get_state(self) -> dict:
        return {
            "position": self._position,
            "held_object": self._held_object,
        }

    def _log(self, result: CommandResult) -> None:
        self._command_log.append({
            "command": result.command,
            "success": result.success,
            "message": result.message,
            "latency_ms": result.latency_ms,
        })

    def _failed(self, command: str, start: float, message: str) -> CommandResult:
        result = CommandResult(
            success=False,
            command=command,
            message=message,
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(result)
        return result

    @staticmethod
    def _elapsed(start: float) -> float:
        return (time.perf_counter() - start) * 1000
