"""
task_planner/safety.py
----------------------
Pre-execution safety guard. Validates a complete ActionPlan against the
physical limits of the workspace *before* the first command reaches a robot.

Why this module exists
----------------------
Until Sprint 6 the only boundary checks in the pipeline lived inside the robot
classes, in move_to(). Three problems followed from that:

  1. The check ran too late. Executor sends commands one at a time and stops on
     the first failure, so a bad coordinate at step 7 was only discovered after
     steps 1-6 had already moved the arm and closed the gripper. In simulation
     that leaves a half-finished plan. On the lab arm it leaves a block in the
     gripper, the arm stopped somewhere over the table, and a person having to
     decide what to do next.

  2. Each robot carried its own hardcoded numbers, and they disagreed with each
     other and with the table. MockRobot accepted 0 <= x,y <= 10 metres, which
     rejected every object on the robot's right (the right tray sits at
     y = -0.45) while happily accepting a target nine metres off the table.
     Kuka_IIWA allowed |y| <= 0.85 and Franka_panda |y| <= 0.90, against a table
     that is 1.5 m deep and therefore ends at y = +/-0.75.

  3. A rectangular box is not a reach envelope. An arm with an 0.80 m reach
     cannot touch the far corner of a box that extends to x = 0.95, y = 0.85,
     but a box check says yes and the IK solver then fails to converge with no
     explanation the operator can act on.

This module replaces those three sets of numbers with one, derives them from
scene_config.yaml so the table and the limits can never drift apart, and runs
the check once over the whole plan before any motion starts.

Usage:
    from task_planner.safety import WorkspaceLimits, validate_plan, SafetyError

    limits = WorkspaceLimits.from_scene_config()      # reads scene_config.yaml
    report = validate_plan(plan, limits)
    if not report.ok:
        print(report.summary())                       # no motion has happened
        return

    # or, to fail loudly:
    assert_plan_safe(plan, limits)                    # raises SafetyError

Emergency stop:
    from task_planner.safety import EmergencyStop

    estop = EmergencyStop()
    estop.install_signal_handler()                    # Ctrl-C becomes a stop
    Executor(robot, emergency_stop=estop).execute(plan)

See documentation/SAFETY_PROCEDURE.md for the procedure the team follows in the
lab. The software stop in this module is a secondary measure. It does not
replace the physical emergency stop on the robot cell.
"""

from __future__ import annotations

import logging
import math
import os
import signal
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Default scene_config.yaml, resolved relative to this file so the module works
# from any working directory.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SCENE_CONFIG = os.path.join(_PROJECT_ROOT, "simulation_backend", "scene_config.yaml")


# ── Limits ─────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class WorkspaceLimits:
    """
    The volume a TCP target is allowed to occupy.

    Two constraints are applied together:

      * an axis-aligned box, taken from the table surface in scene_config.yaml
        and pulled in by `margin_m` so a target is never placed inside a
        perimeter wall;
      * a spherical shell around the robot base, between `min_radius_m` and
        `reach_m`, because an arm cannot reach past its own length and cannot
        fold into its own base column.

    All distances are in metres, matching scene_config.yaml and the rest of the
    pipeline.

    reach_m defaults to 0.80 m, the nominal reach of the KUKA LBR iiwa 7 R800
    used in the simulation (the R800 designation refers to that reach). This is
    a datasheet figure and should be confirmed against the arm actually
    installed in the lab before the physical runs, together with any reduction
    the end effector adds.
    """

    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    z_max: float
    base:         tuple[float, float, float] = (0.0, 0.0, 0.0)
    reach_m:      float = 0.80
    min_radius_m: float = 0.18
    margin_m:     float = 0.0
    source:       str   = "explicit"

    # ── constructors ──────────────────────────────────────────────────────────

    @classmethod
    def from_scene_config(
        cls,
        config_path: Optional[str] = None,
        margin_m: float = 0.02,
        reach_m: float = 0.80,
        z_max: float = 0.60,
    ) -> "WorkspaceLimits":
        """
        Build limits from the workspace section of scene_config.yaml.

        The table is defined by width_m (X extent), depth_m (Y extent) and
        position (centre of the table surface). The surface itself is z = 0, so
        z_min is 0.0: the TCP is never asked to go below the table. z_max is the
        transit height ceiling, not a table dimension, so it stays a parameter.

        margin_m is taken off every horizontal edge. Perimeter walls are 0.02 m
        thick and sit on the table edge, so the default keeps targets clear of
        the inner wall face.

        Falls back to the documented table geometry (2.0 m x 1.5 m, centred on
        the origin) if the file is missing or unreadable, and says so in
        `source` so the caller can tell the difference.
        """
        path = config_path or _SCENE_CONFIG
        cfg: dict = {}
        # Reported relative to the project root, so logs and evidence output do
        # not carry whatever absolute path the machine happened to use.
        source = os.path.relpath(path, _PROJECT_ROOT) if os.path.isabs(path) else path

        try:
            import yaml  # imported here so safety.py works without PyYAML
            with open(path, "r", encoding="utf-8") as handle:
                cfg = (yaml.safe_load(handle) or {}).get("workspace", {}) or {}
        except Exception as exc:
            logger.warning(
                "[safety] Could not read workspace limits from %s (%s). "
                "Falling back to the documented 2.0 x 1.5 m table.", path, exc
            )
            source = f"fallback (could not read {os.path.basename(path)})"

        width  = float(cfg.get("width_m", 2.0))
        depth  = float(cfg.get("depth_m", 1.5))
        centre = cfg.get("position", [0.0, 0.0, 0.0]) or [0.0, 0.0, 0.0]
        cx, cy = float(centre[0]), float(centre[1])

        return cls(
            x_min   = cx - width / 2 + margin_m,
            x_max   = cx + width / 2 - margin_m,
            y_min   = cy - depth / 2 + margin_m,
            y_max   = cy + depth / 2 - margin_m,
            z_min   = 0.0,
            z_max   = z_max,
            reach_m = reach_m,
            margin_m= margin_m,
            source  = source,
        )

    @classmethod
    def from_bounds(
        cls,
        lo: tuple[float, float, float],
        hi: tuple[float, float, float],
        **kwargs,
    ) -> "WorkspaceLimits":
        """Build limits from the ((x,y,z),(x,y,z)) pair the robot classes use."""
        return cls(
            x_min=lo[0], x_max=hi[0],
            y_min=lo[1], y_max=hi[1],
            z_min=lo[2], z_max=hi[2],
            source=kwargs.pop("source", "explicit bounds"),
            **kwargs,
        )

    # ── queries ───────────────────────────────────────────────────────────────

    def as_bounds(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return ((x_min,y_min,z_min),(x_max,y_max,z_max)) for the robot classes."""
        return ((self.x_min, self.y_min, self.z_min),
                (self.x_max, self.y_max, self.z_max))

    def radius_from_base(self, x: float, y: float, z: float = 0.0) -> float:
        """Straight-line distance from the robot base to a target."""
        bx, by, bz = self.base
        return math.sqrt((x - bx) ** 2 + (y - by) ** 2 + (z - bz) ** 2)

    def reason_for_rejecting(self, x: float, y: float, z: float = 0.0) -> Optional[str]:
        """
        Return a plain-language reason this target is not allowed, or None if it
        is allowed. The reason names the axis, the value and the limit, so an
        operator can read it without opening the code.
        """
        if not all(math.isfinite(v) for v in (x, y, z)):
            return f"target ({x}, {y}, {z}) is not a finite coordinate"

        checks = (
            ("X", x, self.x_min, self.x_max),
            ("Y", y, self.y_min, self.y_max),
            ("Z", z, self.z_min, self.z_max),
        )
        for axis, value, lo, hi in checks:
            if value < lo:
                return (f"{axis}={value:.3f} m is below the workspace minimum "
                        f"{lo:.3f} m")
            if value > hi:
                return (f"{axis}={value:.3f} m is beyond the workspace maximum "
                        f"{hi:.3f} m")

        radius = self.radius_from_base(x, y, z)
        if radius > self.reach_m:
            return (f"target is {radius:.3f} m from the robot base, past the "
                    f"{self.reach_m:.3f} m reach of the arm")
        if radius < self.min_radius_m:
            return (f"target is {radius:.3f} m from the robot base, inside the "
                    f"{self.min_radius_m:.3f} m keep-out around the base column")
        return None

    def contains(self, x: float, y: float, z: float = 0.0) -> bool:
        """True when a target is inside every limit."""
        return self.reason_for_rejecting(x, y, z) is None

    def describe(self) -> str:
        """One-line description for logs and operator output."""
        return (f"X [{self.x_min:.2f}, {self.x_max:.2f}] m, "
                f"Y [{self.y_min:.2f}, {self.y_max:.2f}] m, "
                f"Z [{self.z_min:.2f}, {self.z_max:.2f}] m, "
                f"reach {self.reach_m:.2f} m from base {tuple(self.base)}")


# ── Findings ───────────────────────────────────────────────────────────────────
@dataclass
class SafetyViolation:
    """One rejected command."""
    step:     int
    command:  str
    reason:   str
    position: Optional[tuple[float, float, float]] = None

    def __str__(self) -> str:
        where = (f" at ({self.position[0]:.3f}, {self.position[1]:.3f}, "
                 f"{self.position[2]:.3f})") if self.position else ""
        return f"Step {self.step} ({self.command}){where}: {self.reason}"


@dataclass
class SafetyReport:
    """Result of checking one plan. `ok` is False if anything was rejected."""
    ok:              bool
    violations:      list[SafetyViolation] = field(default_factory=list)
    positions_checked: int                 = 0
    steps_checked:     int                 = 0
    limits:          Optional[WorkspaceLimits] = None

    def summary(self) -> str:
        """Multi-line operator-facing summary."""
        head = (f"Safety check: {self.steps_checked} steps, "
                f"{self.positions_checked} positions validated against "
                f"{self.limits.describe() if self.limits else 'no limits'}")
        if self.ok:
            return head + "\n  PASS - plan is inside the workspace."
        lines = [head, f"  BLOCKED - {len(self.violations)} unsafe target(s), "
                       f"no motion was started:"]
        lines.extend(f"    - {v}" for v in self.violations)
        return "\n".join(lines)


class SafetyError(RuntimeError):
    """Raised when a plan is rejected. Carries the report."""

    def __init__(self, report: SafetyReport):
        self.report = report
        first = report.violations[0] if report.violations else "unknown violation"
        super().__init__(
            f"Plan rejected by the pre-execution safety check "
            f"({len(report.violations)} unsafe target(s)). First: {first}"
        )


# ── Plan validation ────────────────────────────────────────────────────────────
def validate_plan(plan, limits: Optional[WorkspaceLimits] = None) -> SafetyReport:
    """
    Check every target position in an ActionPlan against `limits`.

    Runs over the whole plan rather than stopping at the first problem, so the
    operator sees every unsafe coordinate in one pass instead of fixing them one
    execution at a time. Commands with no target position (PICK, PLACE, WAIT)
    carry no coordinate of their own and are counted but not range-checked; the
    MOVE that precedes them is what positions the arm.

    Returns:
        SafetyReport. `ok` is False if any target was rejected.
    """
    limits = limits or WorkspaceLimits.from_scene_config()

    violations: list[SafetyViolation] = []
    positions = 0
    commands = getattr(plan, "commands", []) or []

    for cmd in commands:
        pos = getattr(cmd, "target_position", None)
        if pos is None:
            continue
        x, y, z = float(pos.x), float(pos.y), float(getattr(pos, "z", 0.0) or 0.0)
        positions += 1

        reason = limits.reason_for_rejecting(x, y, z)
        if reason:
            violations.append(SafetyViolation(
                step=getattr(cmd, "step", 0),
                command=_command_name(cmd),
                reason=reason,
                position=(x, y, z),
            ))

    report = SafetyReport(
        ok=not violations,
        violations=violations,
        positions_checked=positions,
        steps_checked=len(commands),
        limits=limits,
    )

    if report.ok:
        logger.info("[safety] Plan cleared - %d positions inside %s",
                    positions, limits.describe())
    else:
        logger.error("[safety] Plan blocked before execution - %d unsafe target(s).",
                     len(violations))
        for violation in violations:
            logger.error("[safety]   %s", violation)
    return report


def assert_plan_safe(plan, limits: Optional[WorkspaceLimits] = None) -> SafetyReport:
    """validate_plan(), but raise SafetyError instead of returning ok=False."""
    report = validate_plan(plan, limits)
    if not report.ok:
        raise SafetyError(report)
    return report


def _command_name(cmd) -> str:
    """Readable command name, whether command_type is an enum or a string."""
    value = getattr(cmd, "command_type", "unknown")
    return getattr(value, "value", str(value)).upper()


# ── Emergency stop ─────────────────────────────────────────────────────────────
class EmergencyStop:
    """
    A software stop flag shared between the operator and the Executor.

    The Executor checks it before each command and stops the plan at the next
    command boundary, so the arm is never interrupted part-way through a motion
    it has already been told to make.

    This is a secondary measure. It depends on the Python process still running
    and on the controller still accepting commands, so it cannot be relied on in
    the cases a stop matters most. The physical emergency stop on the robot cell
    is the primary measure and is the one to use when anything is wrong. See
    documentation/SAFETY_PROCEDURE.md.
    """

    def __init__(self) -> None:
        self._triggered = False
        self._reason: Optional[str] = None
        self._previous_handler = None

    # ── state ─────────────────────────────────────────────────────────────────

    @property
    def triggered(self) -> bool:
        return self._triggered

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    def trigger(self, reason: str = "stop requested by operator") -> None:
        """Request a stop. Safe to call more than once; the first reason wins."""
        if not self._triggered:
            self._triggered = True
            self._reason = reason
            logger.critical("[safety] EMERGENCY STOP - %s", reason)

    def clear(self) -> None:
        """Clear the flag. Only after the cause has been dealt with."""
        if self._triggered:
            logger.warning("[safety] Emergency stop cleared (was: %s).", self._reason)
        self._triggered = False
        self._reason = None

    def check(self) -> None:
        """Raise EmergencyStopped if a stop has been requested."""
        if self._triggered:
            raise EmergencyStopped(self._reason or "stop requested")

    # ── Ctrl-C ────────────────────────────────────────────────────────────────

    def install_signal_handler(self, sig=signal.SIGINT) -> None:
        """
        Make Ctrl-C request a stop instead of raising KeyboardInterrupt in the
        middle of a motion. A second Ctrl-C restores the default handler so the
        operator can always kill the process outright.
        """
        def handler(signum, frame):
            if self._triggered:
                signal.signal(sig, signal.SIG_DFL)
                logger.critical("[safety] Second interrupt - handing back to the OS.")
                raise KeyboardInterrupt
            self.trigger("operator pressed Ctrl-C")

        try:
            self._previous_handler = signal.signal(sig, handler)
        except ValueError:
            # Not the main thread; nothing to install.
            logger.debug("[safety] Signal handler not installed (not main thread).")

    def restore_signal_handler(self, sig=signal.SIGINT) -> None:
        """Put the previous signal handler back."""
        if self._previous_handler is not None:
            try:
                signal.signal(sig, self._previous_handler)
            except ValueError:
                pass
            self._previous_handler = None


class EmergencyStopped(RuntimeError):
    """Raised inside the Executor when a stop was requested mid-plan."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Execution stopped by emergency stop: {reason}")


# ── Convenience ────────────────────────────────────────────────────────────────
def default_limits() -> WorkspaceLimits:
    """
    The limits every robot and the Executor share, read once from
    scene_config.yaml. Cached, because the file does not change at runtime.
    """
    global _DEFAULT_LIMITS
    if _DEFAULT_LIMITS is None:
        _DEFAULT_LIMITS = WorkspaceLimits.from_scene_config()
        logger.info("[safety] Workspace limits: %s (from %s)",
                    _DEFAULT_LIMITS.describe(), _DEFAULT_LIMITS.source)
    return _DEFAULT_LIMITS


_DEFAULT_LIMITS: Optional[WorkspaceLimits] = None


def unsafe_positions(positions: Iterable[tuple], limits: Optional[WorkspaceLimits] = None):
    """
    Check loose coordinates rather than a plan. Used by the vision and planner
    tests and by anything that wants to screen a position before building a
    command for it.

    Yields (position, reason) for each rejected position.
    """
    limits = limits or default_limits()
    for pos in positions:
        x, y = float(pos[0]), float(pos[1])
        z = float(pos[2]) if len(pos) > 2 else 0.0
        reason = limits.reason_for_rejecting(x, y, z)
        if reason:
            yield (x, y, z), reason
