"""
test_sprint2.py
---------------
Unit tests for all Sprint 2 modules.
All tests run without API calls or PyBullet.

Run:
    pytest test_sprint2.py -v

Coverage:
    - action_schema.py  (RobotCommand, ActionPlan, plan_to_commands)
    - mock_robot.py     (MockRobot all commands, state, edge cases)
    - executor.py       (Executor success/failure flows)
    - planner.py        (TaskPlanner all action types)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest
from llm_backend.schema import ParsedInstruction, ActionType, ConfidenceLevel
from execution.action_schema import (
    RobotCommand, ActionPlan, CommandType, Position, plan_to_commands
)
from execution.mock_robot import MockRobot, CommandResult
from execution.executor   import Executor
from task_planner.planner import TaskPlanner


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_scene():
    return {
        "objects": [
            {"label": "red block",    "position": (2.5, 1.0)},
            {"label": "blue block",   "position": (3.0, 2.0)},
            {"label": "green block",  "position": (1.5, 3.0)},
            {"label": "yellow block", "position": (4.0, 2.5)},
            {"label": "left tray",    "position": (6.0, 1.0)},
            {"label": "right tray",   "position": (8.0, 1.0)},
            {"label": "workstation",  "position": (5.0, 5.0)},
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
        result = loaded_robot.move_to(3.0, 2.0)
        assert result.success is True
        assert loaded_robot.get_position() == (3.0, 2.0)

    def test_move_to_out_of_bounds(self, loaded_robot):
        result = loaded_robot.move_to(99.0, 99.0)
        assert result.success is False
        assert "outside workspace" in result.message

    def test_move_to_object(self, loaded_robot):
        result = loaded_robot.move_to_object("red block")
        assert result.success is True
        assert loaded_robot.get_position() == (2.5, 1.0)

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
        assert "4.0" in result.message or "4" in result.message

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
        loaded_robot.move_to(1.0, 1.0)
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