"""
tests/test_safety.py
--------------------
S6-9 — pre-execution safety guard.

Covers four things:

  1. WorkspaceLimits reads the table out of scene_config.yaml and rejects
     targets outside the box, past the arm's reach, inside the base keep-out and
     below the table surface.
  2. validate_plan() finds every unsafe target in a plan in one pass, and
     assert_plan_safe() raises instead.
  3. The Executor refuses an unsafe plan before sending a single command — the
     point of the ticket. The robot is asked afterwards whether it moved.
  4. EmergencyStop halts a plan at a command boundary and leaves the completed
     steps intact.

Plus non-regression: the Sprint 5 plan-time checks (gripper still holding,
missing object, missing destination) still fail at plan time, before the safety
check ever sees a plan.
"""

import pytest

from llm_backend.schema import ParsedInstruction, ActionType, ConfidenceLevel
from simulation_backend.action_schema import (
    ActionPlan, CommandType, Position, RobotCommand,
)
from simulation_backend.executor import Executor
from simulation_backend.mock_robot import MockRobot
from task_planner.planner import TaskPlanner
from task_planner.safety import (
    EmergencyStop,
    SafetyError,
    SafetyReport,
    WorkspaceLimits,
    assert_plan_safe,
    default_limits,
    unsafe_positions,
    validate_plan,
)

# The scene the rest of the suite uses, in the same units as scene_config.yaml.
SCENE = {
    "objects": [
        {"label": "red block",    "position": (0.45, -0.20)},
        {"label": "blue block",   "position": (0.25,  0.35)},
        {"label": "green block",  "position": (0.35,  0.12)},
        {"label": "yellow block", "position": (0.25, -0.35)},
        {"label": "left tray",    "position": (0.65,  0.45)},
        {"label": "right tray",   "position": (0.65, -0.45)},
        {"label": "workstation",  "position": (0.80,  0.00)},
    ]
}


def _parsed(action, obj, dest=None, relation=None, raw=None):
    return ParsedInstruction(
        raw_instruction=raw or f"{action} {obj}",
        action=action,
        object_target=obj,
        destination=dest,
        spatial_relation=relation,
        confidence=ConfidenceLevel.HIGH,
    )


def _plan(*positions) -> ActionPlan:
    """Build a MOVE-only plan from a list of (x, y[, z]) targets."""
    commands = []
    for i, pos in enumerate(positions, start=1):
        z = pos[2] if len(pos) > 2 else 0.0
        commands.append(RobotCommand(
            step=i,
            command_type=CommandType.MOVE,
            target_position=Position(x=pos[0], y=pos[1], z=z),
            description=f"move to {pos}",
        ))
    return ActionPlan(instruction="test plan", commands=commands)


# ── 1. Limits ──────────────────────────────────────────────────────────────────
class TestWorkspaceLimits:

    def test_limits_come_from_scene_config(self):
        """The table is 2.0 m x 1.5 m centred on the origin, less the wall margin."""
        limits = WorkspaceLimits.from_scene_config(margin_m=0.02)
        assert limits.x_min == pytest.approx(-0.98)
        assert limits.x_max == pytest.approx(0.98)
        assert limits.y_min == pytest.approx(-0.73)
        assert limits.y_max == pytest.approx(0.73)
        assert limits.z_min == 0.0
        assert "scene_config.yaml" in limits.source

    def test_missing_config_falls_back_and_says_so(self):
        limits = WorkspaceLimits.from_scene_config(config_path="/nonexistent.yaml")
        assert limits.x_max == pytest.approx(0.98)
        assert "fallback" in limits.source

    @pytest.mark.parametrize("label,position", [
        ("red block",    (0.45, -0.20, 0.05)),
        ("blue block",   (0.25,  0.35, 0.05)),
        ("green block",  (0.35,  0.12, 0.05)),
        ("yellow block", (0.25, -0.35, 0.05)),
        ("left tray",    (0.65,  0.45, 0.01)),
        ("right tray",   (0.65, -0.45, 0.01)),
        ("workstation",  (0.80,  0.00, 0.00)),
    ])
    def test_every_scene_object_is_inside_the_limits(self, label, position):
        """
        Nothing the scene actually contains may be rejected. The right tray and
        the red block are the regression cases: both sit at negative Y, which the
        pre-Sprint-6 MockRobot check refused outright.
        """
        reason = default_limits().reason_for_rejecting(*position)
        assert reason is None, f"{label} at {position} was rejected: {reason}"

    @pytest.mark.parametrize("position,expected", [
        ((9.00,  9.00, 0.00), "beyond the workspace maximum"),
        ((-1.50, 0.00, 0.00), "below the workspace minimum"),
        ((0.00,  1.20, 0.00), "beyond the workspace maximum"),
        ((0.60,  0.00, -0.10), "below the workspace minimum"),
        ((0.60,  0.00,  1.50), "beyond the workspace maximum"),
    ])
    def test_targets_outside_the_box_are_rejected(self, position, expected):
        reason = default_limits().reason_for_rejecting(*position)
        assert reason is not None
        assert expected in reason

    def test_target_past_the_arm_reach_is_rejected(self):
        """
        (0.80, 0.15) is inside the table footprint but 0.814 m from the base, so
        a box check passes it and an 0.80 m arm cannot reach it. This is what
        "move the red block to the left of the workstation" plans.
        """
        limits = default_limits()
        reason = limits.reason_for_rejecting(0.80, 0.15, 0.0)
        assert reason is not None
        assert "reach" in reason
        assert limits.radius_from_base(0.80, 0.15) > limits.reach_m

    def test_target_inside_the_base_keepout_is_rejected(self):
        reason = default_limits().reason_for_rejecting(0.05, 0.0, 0.0)
        assert reason is not None
        assert "keep-out" in reason

    def test_non_finite_coordinates_are_rejected(self):
        for bad in (float("nan"), float("inf")):
            assert default_limits().reason_for_rejecting(bad, 0.0, 0.0) is not None

    def test_as_bounds_round_trips(self):
        limits = default_limits()
        lo, hi = limits.as_bounds()
        assert lo == (limits.x_min, limits.y_min, limits.z_min)
        assert hi == (limits.x_max, limits.y_max, limits.z_max)

    def test_unsafe_positions_reports_only_the_bad_ones(self):
        found = list(unsafe_positions([(0.45, -0.20), (9.0, 9.0), (0.65, 0.45)]))
        assert len(found) == 1
        assert found[0][0][:2] == (9.0, 9.0)


# ── 2. Plan validation ─────────────────────────────────────────────────────────
class TestValidatePlan:

    def test_a_good_plan_passes(self):
        report = validate_plan(_plan((0.45, -0.20), (0.65, -0.45)), default_limits())
        assert report.ok
        assert report.violations == []
        assert report.positions_checked == 2

    def test_all_violations_are_reported_not_just_the_first(self):
        """
        One pass, every problem. Before this the operator found them one
        execution at a time, each after the arm had already moved.
        """
        report = validate_plan(
            _plan((0.45, -0.20), (9.0, 9.0), (0.65, -0.45), (0.80, 0.15)),
            default_limits(),
        )
        assert not report.ok
        assert len(report.violations) == 2
        assert [v.step for v in report.violations] == [2, 4]

    def test_violation_names_the_step_the_command_and_the_number(self):
        report = validate_plan(_plan((9.0, 9.0)), default_limits())
        text = str(report.violations[0])
        assert "Step 1" in text
        assert "MOVE" in text
        assert "9.000" in text

    def test_commands_without_a_position_are_counted_not_checked(self):
        plan = ActionPlan(instruction="pick", commands=[
            RobotCommand(step=1, command_type=CommandType.LOCATE, target_object="red block"),
            RobotCommand(step=2, command_type=CommandType.PICK,   target_object="red block"),
            RobotCommand(step=3, command_type=CommandType.WAIT),
        ])
        report = validate_plan(plan, default_limits())
        assert report.ok
        assert report.steps_checked == 3
        assert report.positions_checked == 0

    def test_summary_says_no_motion_was_started(self):
        report = validate_plan(_plan((9.0, 9.0)), default_limits())
        assert "BLOCKED" in report.summary()
        assert "no motion was started" in report.summary()

    def test_assert_plan_safe_raises_and_carries_the_report(self):
        with pytest.raises(SafetyError) as excinfo:
            assert_plan_safe(_plan((9.0, 9.0)), default_limits())
        assert isinstance(excinfo.value.report, SafetyReport)
        assert excinfo.value.report.violations

    def test_assert_plan_safe_returns_the_report_when_safe(self):
        report = assert_plan_safe(_plan((0.45, -0.20)), default_limits())
        assert report.ok


# ── 3. The Executor refuses an unsafe plan before moving ───────────────────────
class TestExecutorSafetyGate:

    def test_unsafe_plan_is_refused_with_no_commands_sent(self):
        """
        The whole point of S6-9. Step 1 is reachable and step 2 is not. The old
        pipeline executed step 1 and then failed; this one sends nothing.
        """
        robot = MockRobot()
        robot.load_scene(SCENE)
        start = robot.get_position()

        result = Executor(robot, safety_limits=default_limits()).execute(
            _plan((0.45, -0.20), (9.0, 9.0)), verbose=False,
        )

        assert not result.success
        assert result.blocked_by_safety
        assert result.step_results == []
        assert result.steps_completed == 0
        assert robot.get_position() == start, "the arm moved despite an unsafe plan"
        assert "safety check" in result.failed_reason.lower()

    def test_safe_plan_still_executes(self):
        robot = MockRobot()
        robot.load_scene(SCENE)
        result = Executor(robot, safety_limits=default_limits()).execute(
            _plan((0.45, -0.20), (0.65, -0.45)), verbose=False,
        )
        assert result.success
        assert result.steps_completed == 2
        assert result.safety_report is not None and result.safety_report.ok

    def test_gate_is_off_when_no_limits_are_supplied(self):
        """Back-compat: callers written before S6-9 behave exactly as they did."""
        robot = MockRobot()
        robot.load_scene(SCENE)
        result = Executor(robot).execute(_plan((0.45, -0.20)), verbose=False)
        assert result.safety_report is None
        assert result.success

    def test_failing_step_is_reported_as_the_step_number(self):
        robot = MockRobot()
        robot.load_scene(SCENE)
        result = Executor(robot, safety_limits=default_limits()).execute(
            _plan((0.45, -0.20), (0.65, -0.45), (0.80, 0.15)), verbose=False,
        )
        assert result.failed_step == 3


# ── 4. Emergency stop ──────────────────────────────────────────────────────────
class TestEmergencyStop:

    def test_armed_stop_prevents_the_plan_from_starting(self):
        robot = MockRobot()
        robot.load_scene(SCENE)
        start = robot.get_position()

        estop = EmergencyStop()
        estop.trigger("bench test")

        result = Executor(robot, emergency_stop=estop).execute(
            _plan((0.45, -0.20), (0.65, -0.45)), verbose=False,
        )

        assert not result.success
        assert result.stopped
        assert result.step_results == []
        assert robot.get_position() == start

    def test_stop_mid_plan_halts_at_the_next_command_boundary(self):
        """
        Completed steps stay completed. The arm is never cut off part-way through
        a motion it has already been told to make.
        """
        robot = MockRobot()
        robot.load_scene(SCENE)
        estop = EmergencyStop()

        executor = Executor(robot, emergency_stop=estop)
        original = executor._execute_command

        def stop_after_first(cmd):
            outcome = original(cmd)
            if cmd.step == 1:
                estop.trigger("operator pressed the stop during step 1")
            return outcome

        executor._execute_command = stop_after_first
        result = executor.execute(_plan((0.45, -0.20), (0.65, -0.45), (0.25, 0.35)),
                                  verbose=False)

        assert not result.success
        assert result.stopped
        assert result.steps_completed == 1
        assert result.failed_step == 2
        assert "operator pressed the stop" in result.failed_reason

    def test_first_reason_wins_and_clear_resets(self):
        estop = EmergencyStop()
        estop.trigger("first")
        estop.trigger("second")
        assert estop.reason == "first"
        estop.clear()
        assert not estop.triggered and estop.reason is None

    def test_ctrl_c_arms_the_stop_instead_of_killing_the_process(self):
        """
        The README and the safety procedure both tell the operator that Ctrl-C
        arms the stop during a plan. This asserts the handler is real, because a
        safety document that promises a behaviour nobody wired up is worse than
        one that promises nothing.
        """
        import os
        import signal as signal_module

        estop = EmergencyStop()
        estop.install_signal_handler()
        try:
            os.kill(os.getpid(), signal_module.SIGINT)
        finally:
            estop.restore_signal_handler()

        assert estop.triggered
        assert "Ctrl-C" in (estop.reason or "")

    def test_restore_puts_the_previous_handler_back(self):
        """
        Ctrl-C at the interactive prompt must still quit the program, so the
        handler is installed around execution only and removed afterwards.
        """
        import signal as signal_module

        before = signal_module.getsignal(signal_module.SIGINT)
        estop = EmergencyStop()
        estop.install_signal_handler()
        assert signal_module.getsignal(signal_module.SIGINT) is not before
        estop.restore_signal_handler()
        assert signal_module.getsignal(signal_module.SIGINT) is before

    def test_cleared_stop_lets_the_plan_run(self):
        robot = MockRobot()
        robot.load_scene(SCENE)
        estop = EmergencyStop()
        estop.trigger("armed")
        estop.clear()
        result = Executor(robot, emergency_stop=estop).execute(
            _plan((0.45, -0.20)), verbose=False,
        )
        assert result.success and not result.stopped


# ── 5. Robots share one definition of the workspace ────────────────────────────
class TestRobotBoundsAreShared:

    def test_mockrobot_accepts_objects_on_the_robot_right(self):
        """
        Regression. The pre-Sprint-6 check was `0 <= y <= 10`, so the right tray
        at y = -0.45 and the red block at y = -0.20 were both unreachable.
        """
        robot = MockRobot()
        robot.load_scene(SCENE)
        for x, y in ((0.65, -0.45), (0.45, -0.20), (0.25, -0.35)):
            assert robot.move_to(x, y).success, f"({x}, {y}) was rejected"

    def test_mockrobot_rejects_a_target_off_the_table(self):
        """The same check used to accept this: nine metres from a 2 m table."""
        robot = MockRobot()
        robot.load_scene(SCENE)
        assert not robot.move_to(9.0, 9.0).success

    def test_mockrobot_uses_the_shared_limits_by_default(self):
        assert MockRobot()._limits is default_limits()

    def test_legacy_tuple_workspace_still_behaves_as_before(self):
        """Callers written before S6-9 are not broken by the change."""
        robot = MockRobot(workspace=(10.0, 10.0))
        robot.load_scene(SCENE)
        assert robot.move_to(9.0, 9.0).success

    def test_robot_base_bounds_come_from_the_shared_limits(self):
        """
        Every RobotBase subclass inherits the same box, so Kuka, Franka and any
        robot added later cannot drift apart from the table again.
        """
        from simulation_backend.robots.robot_base import RobotBase
        stub = _Stub()
        assert RobotBase._workspace_bounds(stub) == default_limits().as_bounds()
        assert RobotBase._within_bounds(stub, 0.65, -0.45, 0.01) is True
        assert RobotBase._within_bounds(stub, 9.00,  9.00, 0.00) is False
        assert RobotBase._within_bounds(stub, 0.80,  0.15, 0.00) is False

    def test_franka_keeps_its_own_longer_reach(self):
        """Franka Panda reaches 855 mm, so it overrides only the reach."""
        from simulation_backend.robots.Franka_panda import FrankaPanda
        limits = FrankaPanda._safety_limits(_Stub())  # noqa: SLF001
        assert limits.reach_m == pytest.approx(0.855)
        assert limits.as_bounds()[1][0] == pytest.approx(default_limits().x_max)


class _Stub:
    """
    Minimal stand-in so the bound helpers can be called without PyBullet.

    Borrows the helpers straight off the classes under test, which is the point:
    nothing about the workspace limits should need a physics client, a URDF or a
    connected robot to be checked.
    """

    def _safety_limits(self):
        from simulation_backend.robots.robot_base import RobotBase
        return RobotBase._safety_limits(self)


# ── 6. Sprint 5 plan-time checks still work ────────────────────────────────────
class TestSprint5ChecksStillWork:

    def setup_method(self):
        self.planner = TaskPlanner()

    def test_missing_object_still_fails_at_plan_time(self):
        with pytest.raises(ValueError):
            self.planner.generate_plan(
                _parsed(ActionType.PICK, "purple block"), SCENE,
            )

    def test_missing_destination_still_fails_at_plan_time(self):
        with pytest.raises(ValueError):
            self.planner.generate_plan(
                _parsed(ActionType.PICK, "red block", dest="loading dock",
                        relation="in"),
                SCENE,
            )

    def test_gripper_still_held_still_fails_at_plan_time(self):
        """Two picks with no place between them. Caught before the safety check."""
        with pytest.raises(ValueError) as excinfo:
            self.planner.plan_multi_step(
                [_parsed(ActionType.PICK, "red block"),
                 _parsed(ActionType.PICK, "blue block")],
                SCENE,
            )
        assert "holding" in str(excinfo.value).lower()

    def test_a_normal_plan_passes_both_gates(self):
        """Plan-time checks and the safety check agree on a valid instruction."""
        plan = self.planner.generate_plan(
            _parsed(ActionType.PICK, "red block", dest="right tray",
                    relation="in", raw="put the red block in the right tray"),
            SCENE,
        )
        report = validate_plan(plan, default_limits())
        assert report.ok, report.summary()
        assert report.positions_checked > 0
