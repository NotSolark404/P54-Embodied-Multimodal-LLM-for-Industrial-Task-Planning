"""
executor.py
-----------
Execution module — runs an ActionPlan on a robot (mock or real).

Takes an ActionPlan from the task planner and executes each command
sequentially, logging results to the pipeline tracker at each step.

Designed so that MockRobot can be swapped for a real PyBullet robot
with zero changes to this file.

Usage:
    from execution.executor import Executor
    from execution.mock_robot import MockRobot
    from execution.action_schema import ActionPlan

    robot    = MockRobot()
    robot.load_scene(scene)
    executor = Executor(robot)

    results = executor.execute(plan)
    executor.print_results(results)
"""

import logging
import time
from typing import Optional

from execution.action_schema import ActionPlan, CommandType, RobotCommand
from execution.mock_robot import MockRobot, CommandResult

logger = logging.getLogger(__name__)


# ── Execution result ───────────────────────────────────────────────────────────
from dataclasses import dataclass, field


@dataclass
class ExecutionResult:
    plan:           ActionPlan
    step_results:   list[CommandResult]
    success:        bool
    failed_step:    Optional[int]   = None
    failed_reason:  Optional[str]   = None
    total_latency_ms: float         = 0.0

    @property
    def steps_completed(self) -> int:
        return sum(r.success for r in self.step_results)


class Executor:
    """
    Executes an ActionPlan on a robot instance step by step.

    Args:
        robot:   A MockRobot (or real robot with the same interface)
        tracker: Optional PipelineTracker for cross-domain logging
        task_id: Optional task_id for tracker
    """

    def __init__(self, robot: MockRobot, tracker=None, task_id: Optional[str] = None):
        self.robot   = robot
        self.tracker = tracker
        self.task_id = task_id

    def execute(self, plan: ActionPlan, verbose: bool = True) -> ExecutionResult:
        """
        Execute all steps in the ActionPlan sequentially.
        Stops on first failure and returns a detailed ExecutionResult.

        Args:
            plan:    The ActionPlan to execute
            verbose: Print step-by-step progress

        Returns:
            ExecutionResult with per-step results and overall success/failure
        """
        if verbose:
            plan.print_plan()
            print("Executing plan...\n")

        step_results = []
        total_start  = time.perf_counter()

        for cmd in plan.commands:
            if verbose:
                print(f"  Step {cmd.step}: {cmd.command_type.value.upper()} "
                      f"{'«' + cmd.target_object + '»' if cmd.target_object else ''}", end=" ", flush=True)

            result = self._execute_command(cmd)
            step_results.append(result)

            if verbose:
                print(result.message if result.success else f"FAILED — {result.message}")

            # Log to tracker if available
            if self.tracker and self.task_id:
                self.tracker.record(
                    self.task_id,
                    "execution",
                    status="success" if result.success else "failed",
                    payload={"step": cmd.step, "command": cmd.command_type.value, "result": result.message},
                    error=result.message if not result.success else None,
                    latency_ms=result.latency_ms,
                )

            # Stop on failure
            if not result.success:
                total_ms = (time.perf_counter() - total_start) * 1000
                if verbose:
                    print(f"\n  ✗ Execution failed at step {cmd.step}: {result.message}\n")
                return ExecutionResult(
                    plan=plan,
                    step_results=step_results,
                    success=False,
                    failed_step=cmd.step,
                    failed_reason=result.message,
                    total_latency_ms=total_ms,
                )

        total_ms = (time.perf_counter() - total_start) * 1000

        if verbose:
            print(f"\n  ✓ Plan completed successfully in {total_ms:.0f}ms\n")

        return ExecutionResult(
            plan=plan,
            step_results=step_results,
            success=True,
            total_latency_ms=total_ms,
        )

    def _execute_command(self, cmd: RobotCommand) -> CommandResult:
        """Route a single RobotCommand to the correct robot method."""
        ct = cmd.command_type

        if ct == CommandType.LOCATE:
            return self.robot.locate(cmd.target_object or "")

        elif ct == CommandType.MOVE:
            if cmd.target_object:
                return self.robot.move_to_object(cmd.target_object)
            elif cmd.target_position:
                return self.robot.move_to(cmd.target_position.x, cmd.target_position.y)
            else:
                return CommandResult(
                    success=False, command="move",
                    message="Move command has no target object or position"
                )

        elif ct == CommandType.PICK:
            return self.robot.pick(cmd.target_object or "")

        elif ct == CommandType.PLACE:
            return self.robot.place(cmd.target_object or "")

        elif ct == CommandType.WAIT:
            duration = cmd.parameters.get("duration", 1.0)
            time.sleep(duration)
            return CommandResult(
                success=True, command="wait",
                message=f"Waited {duration}s"
            )

        else:
            return CommandResult(
                success=False, command=str(ct),
                message=f"Unknown command type: {ct}"
            )

    def print_results(self, results: ExecutionResult) -> None:
        """Print a summary of execution results."""
        print(f"\n{'═'*55}")
        print(f"  Execution Summary")
        print(f"{'═'*55}")
        print(f"  Status:          {'✓ SUCCESS' if results.success else '✗ FAILED'}")
        print(f"  Steps completed: {results.steps_completed} / {results.plan.total_steps}")
        print(f"  Total time:      {results.total_latency_ms:.0f}ms")
        if results.failed_step:
            print(f"  Failed at step:  {results.failed_step}")
            print(f"  Reason:          {results.failed_reason}")
        print(f"{'═'*55}\n")