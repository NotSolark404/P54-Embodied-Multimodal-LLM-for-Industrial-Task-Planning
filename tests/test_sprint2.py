"""
test_sprint2.py
---------------
Unit tests for all Sprint 2 modules.
All tests run without API calls or PyBullet.

Run:
    pytest tests/test_sprint2.py -v

Coverage:
    - simulation_backend/action_schema.py  (RobotCommand, ActionPlan, plan_to_commands)
    - simulation_backend/mock_robot.py     (MockRobot all commands, state, edge cases)
    - simulation_backend/executor.py       (Executor success/failure flows)
    - task_planner/planner.py              (TaskPlanner all action types)
"""

import pytest
from llm_backend.schema import ParsedInstruction, ActionType, ConfidenceLevel
from simulation_backend.action_schema import (
    RobotCommand, ActionPlan, CommandType, Position, plan_to_commands
)
from simulation_backend.mock_robot import MockRobot, CommandResult
from simulation_backend.executor   import Executor
from task_planner.planner import TaskPlanner


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_scene():
    """
    The scene as scene_config.yaml defines it, in metres.

    S6-10: this fixture used to describe an invented ten-metre workspace — the
    red block at (2.5, 1.0), the right tray at (8.0, 1.0) — from before the
    project settled on metres and a 2.0 x 1.5 m table. Those coordinates are now
    outside the validated workspace, so a suite built on them passed while
    testing a world the lab arm will never see. The positions below are the ones
    in simulation_backend/scene_config.yaml.
    """
    return {
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

@pytest.fixture
def loaded_robot(sample_scene):
    robot = MockRobot()
    robot.load_scene(sample_scene)
    return robot

@pytest.fixture
def pick_instruction():
    return ParsedInstruction(
        action=ActionType.PICK,
        object_target="red block",
        destination=None,
        confidence=ConfidenceLevel.HIGH,
        raw_instruction="pick up the red block",
    )

@pytest.fixture
def place_instruction():
    return ParsedInstruction(
        action=ActionType.PLACE,
        object_target="blue block",
        destination="left tray",
        spatial_relation="in",
        confidence=ConfidenceLevel.HIGH,
        raw_instruction="place the blue block in the left tray",
    )

@pytest.fixture
def locate_instruction():
    return ParsedInstruction(
        action=ActionType.LOCATE,
        object_target="yellow block",
        confidence=ConfidenceLevel.HIGH,
        raw_instruction="locate the yellow block",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ACTION SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestActionSchema:

    def test_robot_command_valid(self):
        cmd = RobotCommand(
            step=1,
            command_type=CommandType.PICK,
            target_object="red block",
        )
        assert cmd.step == 1
        assert cmd.command_type == CommandType.PICK
        assert cmd.target_object == "red block"

    def test_position_as_tuple(self):
        pos = Position(x=2.5, y=1.0)
        assert pos.as_tuple() == (2.5, 1.0, 0.0)

    def test_action_plan_total_steps(self):
        plan = ActionPlan(
            instruction="pick up the red block",
            commands=[
                RobotCommand(step=1, command_type=CommandType.LOCATE, target_object="red block"),
                RobotCommand(step=2, command_type=CommandType.MOVE,   target_object="red block"),
                RobotCommand(step=3, command_type=CommandType.PICK,   target_object="red block"),
            ]
        )
        assert plan.total_steps == 3

    def test_command_summary(self):
        cmd = RobotCommand(
            step=1, command_type=CommandType.MOVE,
            target_object="red block",
            target_position=Position(x=2.5, y=1.0),
        )
        summary = cmd.summary()
        assert "Step 1" in summary
        assert "MOVE" in summary

    def test_plan_to_commands_simple(self):
        steps = [
            {"step": 1, "command": "locate", "target": "red block", "position": (2.5, 1.0)},
            {"step": 2, "command": "move",   "target": (2.5, 1.0)},
            {"step": 3, "command": "pick",   "target": "red block"},
        ]
        plan = plan_to_commands(steps, "pick up the red block")
        assert plan.total_steps == 3
        assert plan.commands[0].command_type == CommandType.LOCATE
        assert plan.commands[1].command_type == CommandType.MOVE
        assert plan.commands[2].command_type == CommandType.PICK

    def test_plan_to_commands_with_task_id(self):
        steps = [{"step": 1, "command": "locate", "target": "red block"}]
        plan  = plan_to_commands(steps, "test", task_id="abc123")
        assert plan.task_id == "abc123"

    def test_all_command_types_valid(self):
        for ct in CommandType:
            cmd = RobotCommand(step=1, command_type=ct)
            assert cmd.command_type == ct


# ═══════════════════════════════════════════════════════════════════════════════
# MOCK ROBOT TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestMockRobot:

    def test_scene_loads_correctly(self, loaded_robot, sample_scene):
        obj_map = loaded_robot.get_object_map()
        assert len(obj_map) == len(sample_scene["objects"])
        assert "red block" in obj_map

    def test_move_to_valid_position(self, loaded_robot):
        result = loaded_robot.move_to(0.35, 0.12)
        assert result.success is True
        assert loaded_robot.get_position() == (0.35, 0.12)

    def test_move_to_out_of_bounds(self, loaded_robot):
        result = loaded_robot.move_to(99.0, 99.0)
        assert result.success is False
        assert "beyond the workspace maximum" in result.message

    def test_move_to_negative_y_is_allowed(self, loaded_robot):
        """
        S6-9 regression. The old check was `0 <= y <= 10`, which refused every
        object on the robot's right — the right tray at y = -0.45 and the red
        block at y = -0.20 — while accepting a target nine metres off the table.
        """
        assert loaded_robot.move_to(0.65, -0.45).success is True

    def test_move_to_object_is_boundary_checked(self, loaded_robot):
        """
        S6-9 regression. move_to_object() used to set the arm position directly,
        with no boundary check, and the Executor routes every planned MOVE
        through it, so the check in move_to() was never reached in a real run.
        """
        loaded_robot.load_scene({
            "objects": [{"label": "stray block", "position": (9.0, 9.0)}]
        })
        result = loaded_robot.move_to_object("stray block")
        assert result.success is False
        assert "not reachable" in result.message

    def test_move_to_object(self, loaded_robot):
        result = loaded_robot.move_to_object("red block")
        assert result.success is True
        assert loaded_robot.get_position() == (0.45, -0.20)

    def test_move_to_unknown_object(self, loaded_robot):
        result = loaded_robot.move_to_object("purple block")
        assert result.success is False

    def test_pick_success(self, loaded_robot):
        result = loaded_robot.pick("red block")
        assert result.success is True
        assert loaded_robot.get_held_object() == "red block"

    def test_pick_unknown_object(self, loaded_robot):
        result = loaded_robot.pick("purple block")
        assert result.success is False

    def test_pick_when_already_holding(self, loaded_robot):
        loaded_robot.pick("red block")
        result = loaded_robot.pick("blue block")
        assert result.success is False
        assert "already holding" in result.message.lower()

    def test_place_success(self, loaded_robot):
        loaded_robot.pick("red block")
        result = loaded_robot.place("left tray")
        assert result.success is True
        assert loaded_robot.get_held_object() is None

    def test_place_without_holding(self, loaded_robot):
        result = loaded_robot.place("left tray")
        assert result.success is False

    def test_place_unknown_location(self, loaded_robot):
        loaded_robot.pick("red block")
        result = loaded_robot.place("nonexistent tray")
        assert result.success is False

    def test_locate_success(self, loaded_robot):
        result = loaded_robot.locate("yellow block")
        assert result.success is True
        assert "0.25" in result.message and "-0.35" in result.message

    def test_locate_unknown_object(self, loaded_robot):
        result = loaded_robot.locate("purple block")
        assert result.success is False

    def test_full_pick_place_sequence(self, loaded_robot):
        r1 = loaded_robot.move_to_object("red block")
        r2 = loaded_robot.pick("red block")
        r3 = loaded_robot.move_to_object("left tray")
        r4 = loaded_robot.place("left tray")
        assert all(r.success for r in [r1, r2, r3, r4])
        assert loaded_robot.get_held_object() is None

    def test_robot_reset(self, loaded_robot):
        loaded_robot.pick("red block")
        loaded_robot.reset()
        assert loaded_robot.get_held_object() is None
        assert loaded_robot.get_position() == (0.0, 0.0)
        assert loaded_robot.get_object_map() == {}

    def test_command_log_grows(self, loaded_robot):
        loaded_robot.move_to(0.45, -0.20)
        loaded_robot.pick("red block")
        assert len(loaded_robot.get_command_log()) == 2

    def test_case_insensitive_object_lookup(self, loaded_robot):
        result = loaded_robot.pick("RED BLOCK")
        assert result.success is True


# ═══════════════════════════════════════════════════════════════════════════════
# EXECUTOR TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestExecutor:

    def _make_plan(self, steps_data: list, instruction: str = "test") -> ActionPlan:
        return plan_to_commands(steps_data, instruction)

    def test_simple_locate_plan_succeeds(self, loaded_robot):
        plan = self._make_plan([
            {"step": 1, "command": "locate", "target": "red block"}
        ], "locate the red block")
        executor = Executor(loaded_robot)
        result   = executor.execute(plan, verbose=False)
        assert result.success is True
        assert result.steps_completed == 1

    def test_full_pick_place_plan_succeeds(self, loaded_robot):
        plan = self._make_plan([
            {"step": 1, "command": "locate", "target": "red block",  "position": (2.5, 1.0)},
            {"step": 2, "command": "move",   "target": "red block"},
            {"step": 3, "command": "pick",   "target": "red block"},
            {"step": 4, "command": "move",   "target": "left tray"},
            {"step": 5, "command": "place",  "target": "left tray"},
        ], "pick up the red block and place it in the left tray")
        executor = Executor(loaded_robot)
        result   = executor.execute(plan, verbose=False)
        assert result.success is True
        assert result.steps_completed == 5

    def test_plan_fails_on_unknown_object(self, loaded_robot):
        plan = self._make_plan([
            {"step": 1, "command": "pick", "target": "purple block"},
        ], "pick up the purple block")
        executor = Executor(loaded_robot)
        result   = executor.execute(plan, verbose=False)
        assert result.success is False
        assert result.failed_step == 1

    def test_plan_stops_on_first_failure(self, loaded_robot):
        plan = self._make_plan([
            {"step": 1, "command": "pick",  "target": "purple block"},  # fails
            {"step": 2, "command": "place", "target": "left tray"},      # should not run
        ], "test")
        executor = Executor(loaded_robot)
        result   = executor.execute(plan, verbose=False)
        assert result.steps_completed == 0
        assert result.failed_step == 1

    def test_execution_result_has_latency(self, loaded_robot):
        plan = self._make_plan([
            {"step": 1, "command": "locate", "target": "red block"}
        ], "test")
        executor = Executor(loaded_robot)
        result   = executor.execute(plan, verbose=False)
        assert result.total_latency_ms >= 0


# ═══════════════════════════════════════════════════════════════════════════════
# TASK PLANNER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskPlanner:

    def test_pick_plan_generates_steps(self, pick_instruction, sample_scene):
        planner = TaskPlanner()
        plan    = planner.generate_plan(pick_instruction, sample_scene)
        assert plan.total_steps >= 3
        assert plan.commands[0].command_type == CommandType.LOCATE
        assert any(c.command_type == CommandType.PICK for c in plan.commands)

    def test_place_plan_generates_full_sequence(self, place_instruction, sample_scene):
        planner = TaskPlanner()
        plan    = planner.generate_plan(place_instruction, sample_scene)
        types   = [c.command_type for c in plan.commands]
        assert CommandType.LOCATE in types
        assert CommandType.PICK   in types
        assert CommandType.PLACE  in types

    def test_locate_plan_is_single_step(self, locate_instruction, sample_scene):
        planner = TaskPlanner()
        plan    = planner.generate_plan(locate_instruction, sample_scene)
        assert plan.total_steps == 1
        assert plan.commands[0].command_type == CommandType.LOCATE

    def test_pick_with_destination_includes_place(self, sample_scene):
        parsed = ParsedInstruction(
            action=ActionType.PICK,
            object_target="red block",
            destination="left tray",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the red block and place it in the left tray",
        )
        planner = TaskPlanner()
        plan    = planner.generate_plan(parsed, sample_scene)
        types   = [c.command_type for c in plan.commands]
        assert CommandType.PLACE in types

    def test_missing_object_raises(self, sample_scene):
        parsed = ParsedInstruction(
            action=ActionType.PICK,
            object_target="purple block",
            confidence=ConfidenceLevel.LOW,
            raw_instruction="pick up the purple block",
        )
        planner = TaskPlanner()
        with pytest.raises(ValueError, match="not found in scene"):
            planner.generate_plan(parsed, sample_scene)

    def test_plan_preserves_instruction(self, pick_instruction, sample_scene):
        planner = TaskPlanner()
        plan    = planner.generate_plan(pick_instruction, sample_scene)
        assert plan.instruction == pick_instruction.raw_instruction

    def test_plan_with_task_id(self, pick_instruction, sample_scene):
        planner = TaskPlanner()
        plan    = planner.generate_plan(pick_instruction, sample_scene, task_id="test123")
        assert plan.task_id == "test123"

    def test_move_plan_same_as_place(self, sample_scene):
        parsed = ParsedInstruction(
            action=ActionType.MOVE,
            object_target="green block",
            destination="right tray",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="move the green block to the right tray",
        )
        planner = TaskPlanner()
        plan    = planner.generate_plan(parsed, sample_scene)
        assert plan.total_steps >= 3

    def test_full_pipeline_planner_to_executor(self, place_instruction, sample_scene):
        """End-to-end: planner generates plan → executor runs it on mock robot."""
        planner  = TaskPlanner()
        robot    = MockRobot()
        robot.load_scene(sample_scene)
        executor = Executor(robot)

        plan   = planner.generate_plan(place_instruction, sample_scene)
        result = executor.execute(plan, verbose=False)

        assert result.success is True
        assert robot.get_held_object() is None  # object was placed
