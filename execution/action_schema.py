"""
action_schema.py
----------------
PB8-CMD: Robot action command schema.

Defines the data contract between the task planner and the execution module.
All downstream modules import from here — same pattern as schema.py for the LLM module.

Interface contract:
    Task planner  → produces ActionPlan
    Execution     → consumes ActionPlan, sends RobotCommands to robot
    Tracker       → logs each RobotCommand as a pipeline stage event

Usage:
    from execution.action_schema import RobotCommand, ActionPlan, CommandType
    from execution.action_schema import plan_to_commands
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ── Command types ──────────────────────────────────────────────────────────────
class CommandType(str, Enum):
    MOVE  = "move"
    PICK  = "pick"
    PLACE = "place"
    LOCATE = "locate"
    WAIT  = "wait"


# ── Position model ─────────────────────────────────────────────────────────────
class Position(BaseModel):
    x: float = Field(description="X coordinate in workspace units")
    y: float = Field(description="Y coordinate in workspace units")
    z: float = Field(default=0.0, description="Z coordinate (height)")

    def as_tuple(self) -> tuple:
        return (self.x, self.y, self.z)


# ── Single robot command ───────────────────────────────────────────────────────
class RobotCommand(BaseModel):
    """
    A single executable command sent to the robot.

    Example:
        RobotCommand(
            step=1,
            command_type=CommandType.MOVE,
            target_object="red block",
            target_position=Position(x=2.5, y=1.0),
        )
    """
    step:            int          = Field(description="Order of this command in the plan")
    command_type:    CommandType  = Field(description="Type of robot action")
    target_object:   Optional[str] = Field(default=None, description="Object to act on")
    target_position: Optional[Position] = Field(default=None, description="Position to move to")
    parameters:      dict         = Field(default_factory=dict, description="Extra parameters")
    description:     str          = Field(default="", description="Human-readable step description")

    def summary(self) -> str:
        """One-line human readable summary of this command."""
        parts = [f"Step {self.step}: {self.command_type.value.upper()}"]
        if self.target_object:
            parts.append(f"'{self.target_object}'")
        if self.target_position:
            parts.append(f"→ ({self.target_position.x}, {self.target_position.y})")
        return " ".join(parts)


# ── Full action plan ───────────────────────────────────────────────────────────
class ActionPlan(BaseModel):
    """
    An ordered list of RobotCommands produced by the task planner.
    This is what the execution module receives and executes sequentially.
    """
    task_id:      Optional[str]       = Field(default=None, description="Pipeline tracker task ID")
    instruction:  str                 = Field(description="Original natural language instruction")
    commands:     list[RobotCommand]  = Field(description="Ordered list of robot commands")
    total_steps:  int                 = Field(default=0, description="Total number of steps")

    def model_post_init(self, __context) -> None:
        object.__setattr__(self, "total_steps", len(self.commands))

    def print_plan(self) -> None:
        """Pretty print the full action plan."""
        print(f"\n{'─'*55}")
        print(f"  Action Plan — {self.total_steps} steps")
        print(f"  Instruction: {self.instruction}")
        if self.task_id:
            print(f"  Task ID:     {self.task_id}")
        print(f"{'─'*55}")
        for cmd in self.commands:
            print(f"  {cmd.summary()}")
            if cmd.description:
                print(f"    → {cmd.description}")
        print(f"{'─'*55}\n")


# ── Converter: task planner output → ActionPlan ────────────────────────────────
def plan_to_commands(
    plan_steps: list[dict],
    instruction: str,
    task_id: Optional[str] = None,
) -> ActionPlan:
    """
    Convert raw task planner output (list of step dicts) into a validated ActionPlan.

    Args:
        plan_steps:  Output from task_planner.planner.generate_plan()
        instruction: Original instruction string
        task_id:     Optional tracker task ID

    Returns:
        ActionPlan: Validated, ready to send to execution module

    Example input (plan_steps):
        [
            {"step": 1, "command": "locate", "target": "red block", "position": (2.5, 1.0)},
            {"step": 2, "command": "move",   "target": (2.5, 1.0)},
            {"step": 3, "command": "pick",   "target": "red block"},
            {"step": 4, "command": "move",   "target": (4.0, 0.5)},
            {"step": 5, "command": "place",  "target": "left tray"},
        ]
    """
    commands = []
    for step in plan_steps:
        cmd_type = CommandType(step["command"])
        target = step.get("target")

        # Resolve target_object and target_position
        target_object   = None
        target_position = None

        if isinstance(target, str):
            target_object = target
        elif isinstance(target, (tuple, list)) and len(target) >= 2:
            target_position = Position(x=float(target[0]), y=float(target[1]))
        elif isinstance(target, dict) and "x" in target:
            target_position = Position(**target)

        # If position is separately provided
        if "position" in step and step["position"] is not None:
            pos = step["position"]
            if isinstance(pos, (tuple, list)):
                target_position = Position(x=float(pos[0]), y=float(pos[1]))
            elif isinstance(pos, dict):
                target_position = Position(**pos)

        commands.append(RobotCommand(
            step=step["step"],
            command_type=cmd_type,
            target_object=target_object,
            target_position=target_position,
            description=step.get("description", ""),
        ))

    return ActionPlan(
        task_id=task_id,
        instruction=instruction,
        commands=commands,
    )