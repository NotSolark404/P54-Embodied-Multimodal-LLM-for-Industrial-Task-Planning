"""
simulation_backend/robots/Franka_panda.py
-----------------------------------------
Franka Panda 7-DOF robot arm controller for the simulation pipeline.

URDF source: pybullet_data/franka_panda/panda.urdf
Loaded by:   simulation_backend/simulation.py when ROBOT_MODEL=franka

Joint layout (from panda.urdf):
    Index 0-6  : panda_joint1 - panda_joint7   revolute arm joints  force=87N
    Index 7    : panda_joint8                   fixed
    Index 8    : panda_hand_joint               fixed
    Index 9    : panda_finger_joint1            prismatic left finger force=20N
    Index 10   : panda_finger_joint2            prismatic right finger
    Index 11   : panda_grasptarget_hand         fixed (TCP frame, 0.105m below hand)

End-effector link for IK: 11 (panda_grasptarget) - centred between fingertips.

Coordinate frame:
    Robot base at [0.0, 0.0, 0.0]. All objects at x=[0.30, 0.80] are
    within the 0.855m Franka reach. Table surface is at z=0.0.
    Blocks rest at z~0.025-0.05.

Motion strategy - waypointed transit:
    All moves that carry a held object use three waypoints:
        1. Lift straight up to TRANSIT_HEIGHT (0.35m)
        2. Swing to destination XY at TRANSIT_HEIGHT
        3. Descend to approach/place height
    This prevents the arm from dragging the block through the table
    or fighting the rigid constraint at low heights during large swings.

Grasp heights:
    APPROACH_HEIGHT = 0.15 m above object z  (pre-grasp transit target)
    GRASP_HEIGHT    = 0.01 m above object z  (fingertip contact)
    TRANSIT_HEIGHT  = 0.35 m absolute z      (safe carrying height)
    PLACE_HEIGHT    = 0.05 m above dest z    (release height over tray)
    RETRACT_HEIGHT  = 0.25 m above dest z    (post-place clearance)

Environment variables:
    FRANKA_MOVE_STEPS   : max sim steps per move. Default 2000.
    FRANKA_POS_TOL      : TCP convergence tolerance metres. Default 0.025.
    FRANKA_ARM_FORCE    : joint motor force N. Default 87.0.
    FRANKA_MAX_VEL      : joint max velocity rad/s. Default 1.5.
    FRANKA_TRANSIT_Z    : safe carrying height metres. Default 0.35.

Public interface (same as MockRobot):
    load_scene(scene), move_to(), move_to_object(), pick(), place(),
    locate(), reset(), get_position(), get_held_object(), print_state()

Usage (from simulation.py):
    body_id = p.loadURDF("franka_panda/panda.urdf",
                         basePosition=[0.0, 0.0, 0.0],
                         useFixedBase=True)
    robot = FrankaPanda(physics_client=client, body_id=body_id, registry=registry)
    robot.reset()
    robot.load_scene(scene)
"""

import logging
import os
import time
from typing import Optional

import pybullet as p

from simulation_backend.robots.robot_base import RobotBase
from simulation_backend.robots.gripper.franka_hand import FrankaHand
from simulation_backend.simulation_environment.object_registry import ObjectRegistry
from simulation_backend.mock_robot import CommandResult

logger = logging.getLogger(__name__)


class FrankaPanda(RobotBase):
    """
    Franka Panda 7-DOF arm with integrated Franka Hand gripper.

    Key design: move_to_object() and place() both use waypointed transit
    (lift → swing → descend) when the arm is loaded (holding an object).
    This prevents the block from being dragged at low height during large
    lateral swings, which causes IK convergence failures.
    """

    model_name = "franka_panda"

    # ── URDF constants ─────────────────────────────────────────────────────────
    _NUM_ARM_JOINTS  = 7
    _ARM_JOINT_FORCE = 87.0
    _EE_LINK         = 11

    # Standard Franka ready pose
    _HOME_JOINTS = [0.0, -0.785, 0.0, -2.356, 0.0, 1.571, 0.785]

    # IK joint damping
    _IK_DAMPING = [0.1] * 7 + [1.0] * 4

    def __init__(
        self,
        physics_client: int,
        body_id:        int,
        registry:       ObjectRegistry,
        config:         dict = None,
    ) -> None:
        super().__init__(physics_client, body_id, config)

        self._registry      = registry
        self._gripper       = FrankaHand(physics_client, body_id, config)
        self._constraint_id: Optional[int] = None

        # Motion parameters — env vars override config, config overrides defaults
        self._move_steps   = int(float(os.getenv("FRANKA_MOVE_STEPS",  str(self._cfg.get("move_steps",   2000)))))
        self._pos_tol      = float(os.getenv("FRANKA_POS_TOL",         str(self._cfg.get("position_tol", 0.025))))
        self._arm_force    = float(os.getenv("FRANKA_ARM_FORCE",       str(self._cfg.get("arm_force",    self._ARM_JOINT_FORCE))))
        self._max_vel      = float(os.getenv("FRANKA_MAX_VEL",         str(self._cfg.get("max_velocity", 1.5))))
        self._transit_z    = float(os.getenv("FRANKA_TRANSIT_Z",       str(self._cfg.get("transit_z",    0.35))))

        # Fixed height offsets
        self._APPROACH_HEIGHT = float(self._cfg.get("approach_height", 0.15))
        self._GRASP_HEIGHT    = float(self._cfg.get("grasp_height",    0.01))
        self._PLACE_HEIGHT    = float(self._cfg.get("place_height",    0.05))
        self._RETRACT_HEIGHT  = float(self._cfg.get("retract_height",  0.25))

        # Step sleep — controls motion speed in GUI.
        # Default: 1/240 = physics timestep = real-time speed.
        # Set FRANKA_STEP_SLEEP=0 to run at max CPU speed.
        self._step_sleep = float(
            os.getenv("FRANKA_STEP_SLEEP",
                      str(self._cfg.get("step_sleep", 1.0 / 240.0)))
        )

        logger.info(
            f"[franka_panda] Initialised — body_id={body_id}  "
            f"move_steps={self._move_steps}  pos_tol={self._pos_tol}m  "
            f"arm_force={self._arm_force}N  max_vel={self._max_vel}rad/s  "
            f"transit_z={self._transit_z}m  step_sleep={self._step_sleep:.4f}s"
        )

    # ── reset ─────────────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Teleport arm to home pose and open gripper. Safe at startup."""
        if self._constraint_id is not None:
            try:
                p.removeConstraint(self._constraint_id, physicsClientId=self._client)
            except Exception:
                pass
            self._constraint_id = None

        for joint_idx, pos in enumerate(self._HOME_JOINTS):
            p.resetJointState(
                self._body_id, joint_idx, pos, physicsClientId=self._client
            )

        self._gripper.open()
        self._held_object = None
        self._position    = self._read_tcp_position()
        logger.info("[franka_panda] Reset to home pose.")

    # ── move_to ───────────────────────────────────────────────────────────────

    def move_to(self, x: float, y: float, z: float = 0.0) -> CommandResult:
        """
        Move the TCP to world coordinates (x, y, z) via IK + POSITION_CONTROL.

        Single direct move. Does not use waypoints — callers that need
        safe transit should call _move_via_transit() instead.
        """
        start = time.perf_counter()

        if not self._within_bounds(x, y, z):
            return CommandResult(
                success=False, command="move_to",
                message=f"Target ({x:.3f}, {y:.3f}, {z:.3f}) outside workspace bounds.",
                latency_ms=self._elapsed(start),
            )

        target = [x, y, z]

        joint_angles = p.calculateInverseKinematics(
            self._body_id,
            self._EE_LINK,
            targetPosition=target,
            jointDamping=self._IK_DAMPING,
            physicsClientId=self._client,
        )

        for joint_idx in range(self._NUM_ARM_JOINTS):
            p.setJointMotorControl2(
                bodyIndex       = self._body_id,
                jointIndex      = joint_idx,
                controlMode     = p.POSITION_CONTROL,
                targetPosition  = joint_angles[joint_idx],
                force           = self._arm_force,
                maxVelocity     = self._max_vel,
                physicsClientId = self._client,
            )

        reached = self._step_to_target(target, self._move_steps)
        tcp     = self._read_tcp_position()
        self._position = tcp
        lat     = self._elapsed(start)

        msg = (
            f"Moved to ({x:.3f}, {y:.3f}, {z:.3f}) — "
            f"TCP=({tcp[0]:.3f}, {tcp[1]:.3f}, {tcp[2]:.3f})"
            if reached else
            f"TCP did not converge to ({x:.3f}, {y:.3f}, {z:.3f}) "
            f"within {self._move_steps} steps. "
            f"Final TCP=({tcp[0]:.3f}, {tcp[1]:.3f}, {tcp[2]:.3f})"
        )

        result = CommandResult(
            success=reached, command="move_to",
            message=msg, latency_ms=lat, state=self._get_state(),
        )
        self._log(result)
        return result

    # ── move_to_object ────────────────────────────────────────────────────────

    def move_to_object(self, object_name: str) -> CommandResult:
        """
        Move to approach height above the named object.

        When the arm is loaded (holding an object), uses waypointed transit:
            1. Lift to TRANSIT_HEIGHT at current XY
            2. Swing to destination XY at TRANSIT_HEIGHT
            3. Descend to object_z + APPROACH_HEIGHT

        This prevents IK failures from large lateral swings at low heights
        while carrying a block held by a rigid constraint.

        When not loaded, moves directly to the approach height.
        """
        start = time.perf_counter()

        obj = self._find_object(object_name)
        if obj is None:
            return CommandResult(
                success=False, command="move_to_object",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        x, y, z       = obj["position"]
        approach_z    = z + self._APPROACH_HEIGHT

        if self._held_object is not None:
            # Waypointed transit — lift, swing, descend
            r = self._move_via_transit(x, y, approach_z)
        else:
            # Direct move — unloaded arm
            r = self.move_to(x, y, approach_z)

        r.command = "move_to_object"
        r.message = (
            f"Moved above '{object_name}' at ({x:.3f}, {y:.3f}, {approach_z:.3f})"
            if r.success else
            f"Failed to move above '{object_name}': {r.message}"
        )
        self._log(r)
        return r

    # ── pick ──────────────────────────────────────────────────────────────────

    def pick(self, object_name: str) -> CommandResult:
        """
        Full grasp sequence: open → approach → descend → close → constrain → lift.
        All pre-grasp moves are direct (arm is unloaded before pick).
        Lift after grasp uses transit height.
        """
        start = time.perf_counter()

        if self._held_object is not None:
            return CommandResult(
                success=False, command="pick",
                message=f"Already holding '{self._held_object}'. Place it first.",
                latency_ms=self._elapsed(start),
            )

        obj = self._find_object(object_name)
        if obj is None:
            return CommandResult(
                success=False, command="pick",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        if obj.get("held"):
            return CommandResult(
                success=False, command="pick",
                message=f"'{object_name}' is already held.",
                latency_ms=self._elapsed(start),
            )

        x, y, z = obj["position"]

        # Open gripper
        self._gripper.open()

        # Approach — direct, arm is empty
        r = self.move_to(x, y, z + self._APPROACH_HEIGHT)
        if not r.success:
            return CommandResult(
                success=False, command="pick",
                message=f"Approach failed for '{object_name}': {r.message}",
                latency_ms=self._elapsed(start),
            )

        # Descend to grasp height
        r = self.move_to(x, y, z + self._GRASP_HEIGHT)
        if not r.success:
            return CommandResult(
                success=False, command="pick",
                message=f"Descent failed for '{object_name}': {r.message}",
                latency_ms=self._elapsed(start),
            )

        # Close gripper (compliant — stops on contact)
        self._gripper.close(target_width_m=0.0, max_force_n=20.0)
        gripper_state = self._gripper.get_state()

        # Attach object via rigid constraint
        obj_body_id = self._get_object_body_id(object_name)
        if obj_body_id is not None:
            self._constraint_id = p.createConstraint(
                parentBodyUniqueId  = self._body_id,
                parentLinkIndex     = self._EE_LINK,
                childBodyUniqueId   = obj_body_id,
                childLinkIndex      = -1,
                jointType           = p.JOINT_FIXED,
                jointAxis           = [0, 0, 0],
                parentFramePosition = [0, 0, 0.01],
                childFramePosition  = [0, 0, 0],
                physicsClientId     = self._client,
            )
            logger.debug(
                f"[franka_panda] Constraint {self._constraint_id}: "
                f"EE → '{object_name}' (body_id={obj_body_id})"
            )
        else:
            logger.warning(
                f"[franka_panda] body_id not found for '{object_name}' — "
                f"no constraint, object may not follow arm."
            )

        # Mark as held before lift so move_to_object uses transit on next call
        obj["held"]       = True
        self._held_object = object_name

        # Lift to transit height — straight up, then arm is in safe carry pose
        self._move_via_transit(x, y, self._transit_z)

        result = CommandResult(
            success=True, command="pick",
            message=(
                f"Picked '{object_name}' at ({x:.3f}, {y:.3f}, {z:.3f}) — "
                f"width={gripper_state.finger_width_m:.4f}m "
                f"force={gripper_state.contact_force_n:.2f}N"
            ),
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(result)
        logger.info(f"[franka_panda] pick('{object_name}') success.")
        return result

    # ── place ─────────────────────────────────────────────────────────────────

    def place(self, location_name: str) -> CommandResult:
        """
        Full release sequence using waypointed transit:
            1. Transit to above destination (lift → swing → descend to approach)
            2. Descend to place height
            3. Open gripper
            4. Remove constraint
            5. Settle
            6. Retract
        """
        start = time.perf_counter()

        if self._held_object is None:
            return CommandResult(
                success=False, command="place",
                message="Not holding any object.",
                latency_ms=self._elapsed(start),
            )

        dest = self._find_object(location_name)
        if dest is None:
            return CommandResult(
                success=False, command="place",
                message=f"Destination '{location_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        dx, dy, dz    = dest["position"]
        placed_object = self._held_object

        # Transit to above destination — lift, swing, descend
        r = self._move_via_transit(dx, dy, dz + self._APPROACH_HEIGHT)
        if not r.success:
            return CommandResult(
                success=False, command="place",
                message=f"Transit to '{location_name}' failed: {r.message}",
                latency_ms=self._elapsed(start),
            )

        # Descend to release height
        r = self.move_to(dx, dy, dz + self._PLACE_HEIGHT)
        if not r.success:
            return CommandResult(
                success=False, command="place",
                message=f"Descent to '{location_name}' failed: {r.message}",
                latency_ms=self._elapsed(start),
            )

        # Open gripper
        self._gripper.open()

        # Remove constraint — block falls under gravity
        if self._constraint_id is not None:
            try:
                p.removeConstraint(self._constraint_id, physicsClientId=self._client)
                logger.debug(f"[franka_panda] Constraint {self._constraint_id} removed.")
            except Exception as e:
                logger.warning(f"[franka_panda] Could not remove constraint: {e}")
            self._constraint_id = None

        # Settle
        for _ in range(80):
            p.stepSimulation(physicsClientId=self._client)

        # Retract — arm is now unloaded, direct move
        self.move_to(dx, dy, dz + self._RETRACT_HEIGHT)

        # Update state
        held_key = placed_object.lower()
        if held_key in self._object_map:
            self._object_map[held_key]["position"] = (dx, dy, dz)
            self._object_map[held_key]["held"]     = False
        self._held_object = None

        result = CommandResult(
            success=True, command="place",
            message=(
                f"Placed '{placed_object}' at '{location_name}' "
                f"({dx:.3f}, {dy:.3f}, {dz:.3f})"
            ),
            latency_ms=self._elapsed(start),
            state=self._get_state(),
        )
        self._log(result)
        logger.info(f"[franka_panda] place('{location_name}') success.")
        return result

    # ── locate ────────────────────────────────────────────────────────────────

    def locate(self, object_name: str) -> CommandResult:
        """Confirm object exists in the scene. No arm movement."""
        start = time.perf_counter()
        obj   = self._find_object(object_name)

        if obj is None:
            return CommandResult(
                success=False, command="locate",
                message=f"Object '{object_name}' not found in scene.",
                latency_ms=self._elapsed(start),
            )

        pos = obj["position"]
        result = CommandResult(
            success=True, command="locate",
            message=f"Found '{object_name}' at {pos}",
            latency_ms=self._elapsed(start),
            state={"position": pos},
        )
        self._log(result)
        return result

    # ── workspace bounds ──────────────────────────────────────────────────────

    def _workspace_bounds(self) -> tuple[tuple, tuple]:
        """
        The box the TCP is allowed inside, from the shared project limits.

        Franka Panda reach is 855 mm from a base at [0, 0, 0], so the reach limit
        is widened from the project default before the box is returned. The box
        itself comes from the table in scene_config.yaml rather than the
        hardcoded ((0.10, -0.90, 0.00), (0.90, 0.90, 0.60)) this method used to
        return, which permitted |y| up to 0.90 m on a table that ends at 0.75 m.
        """
        return self._safety_limits().as_bounds()

    def _safety_limits(self):
        """Shared WorkspaceLimits with Franka's own 0.855 m reach substituted in."""
        limits = getattr(self, "_limits_cache", None)
        if limits is None:
            import dataclasses
            from task_planner.safety import default_limits
            limits = dataclasses.replace(
                default_limits(), reach_m=0.855, source="scene_config + Franka reach",
            )
            self._limits_cache = limits
        return limits

    # ── private helpers ───────────────────────────────────────────────────────

    def _move_via_transit(
        self,
        dest_x: float,
        dest_y: float,
        dest_z: float,
    ) -> CommandResult:
        """
        Three-waypoint transit move: lift → swing → descend.

        Used whenever the arm carries a held object (rigid constraint active)
        or when large lateral displacement is needed.

        Waypoints:
            1. (current_x, current_y, transit_z) — lift straight up
            2. (dest_x,    dest_y,    transit_z) — swing at safe height
            3. (dest_x,    dest_y,    dest_z   ) — descend to final height

        Each leg uses self.move_to(). Stops and returns failure on the first
        leg that fails.

        Args:
            dest_x, dest_y : Target XY in world metres.
            dest_z         : Target Z in world metres (approach or transit height).

        Returns:
            CommandResult of the last leg (or the failed leg).
        """
        cur_x, cur_y, cur_z = self._position

        # Leg 1 — lift straight up
        if cur_z < self._transit_z - 0.02:
            r = self.move_to(cur_x, cur_y, self._transit_z)
            if not r.success:
                r.message = f"[transit] Lift failed: {r.message}"
                return r

        # Leg 2 — swing laterally at transit height
        r = self.move_to(dest_x, dest_y, self._transit_z)
        if not r.success:
            r.message = f"[transit] Swing failed: {r.message}"
            return r

        # Leg 3 — descend to final height
        r = self.move_to(dest_x, dest_y, dest_z)
        if not r.success:
            r.message = f"[transit] Descent failed: {r.message}"
        return r

    def _read_tcp_position(self) -> tuple[float, float, float]:
        """Read the current world-space TCP position from PyBullet."""
        state = p.getLinkState(
            self._body_id, self._EE_LINK, physicsClientId=self._client
        )
        pos = state[0]
        return (round(pos[0], 5), round(pos[1], 5), round(pos[2], 5))

    def _step_to_target(self, target: list[float], max_steps: int) -> bool:
        """
        Step simulation until TCP is within pos_tol of target.

        Sleeps self._step_sleep seconds after each physics step so motion
        is visible at human speed in the PyBullet GUI. The sleep time is
        set to match the physics timestep (1/240s) by default, making the
        simulation run at approximately real-time speed.

        Set FRANKA_STEP_SLEEP=0 in .env for maximum speed (no sleep).

        Returns True if converged, False if max_steps exhausted.
        """
        tx, ty, tz = target
        for _ in range(max_steps):
            p.stepSimulation(physicsClientId=self._client)
            if self._step_sleep > 0:
                time.sleep(self._step_sleep)
            tcp  = self._read_tcp_position()
            dist = ((tcp[0]-tx)**2 + (tcp[1]-ty)**2 + (tcp[2]-tz)**2) ** 0.5
            if dist < self._pos_tol:
                return True
        return False

    def _get_object_body_id(self, object_name: str) -> Optional[int]:
        """Look up PyBullet body_id for an object label via the registry."""
        entry = self._registry.get_by_label(object_name)
        if entry is not None:
            return entry.body_id
        name_lower = object_name.lower()
        for e in self._registry.all_entries():
            label_lower = e.label.lower()
            if name_lower in label_lower or label_lower in name_lower:
                return e.body_id
        logger.warning(f"[franka_panda] '{object_name}' not found in registry.")
        return None
