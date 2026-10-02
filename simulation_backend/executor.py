"""
executor.py
-----------

Takes an ActionPlan from the task planner and executes each command
sequentially, logging results to the pipeline tracker at each step.

Designed so that MockRobot can be swapped for a real PyBullet robot
with zero changes to this file.

Sprint 6 (S6-9) added two safety gates:

    * a pre-flight check. Before the first command is sent, the whole plan is
      validated against the workspace limits in task_planner/safety.py. A plan
      with an unreachable target is refused outright, so the arm never starts a
      sequence it cannot finish. Pass safety_limits=None to skip the gate, which
      is what the pre-Sprint-6 tests do.
    * an emergency stop. If an EmergencyStop is supplied, it is checked before
      every command, so a stop request halts the plan at the next command
      boundary rather than part-way through a motion already in progress.

Usage:
    from simulation_backend.executor import Executor
    from simulation_backend.mock_robot import MockRobot
    from simulation_backend.action_schema import ActionPlan

    robot    = MockRobot()
    robot.load_scene(scene)
    executor = Executor(robot)

    results = executor.execute(plan)
    executor.print_results(results)
"""

import logging
import time
from typing import Optional

from simulation_backend.action_schema import ActionPlan, CommandType, RobotCommand
from simulation_backend.mock_robot import MockRobot, CommandResult
from task_planner.safety import (
    EmergencyStop,
    EmergencyStopped,
    SafetyReport,
    WorkspaceLimits,
    validate_plan,
)

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
    safety_report:  Optional["SafetyReport"] = None
    stopped:        bool            = False

    @property
    def steps_completed(self) -> int:
        return sum(r.success for r in self.step_results)

    @property
    def blocked_by_safety(self) -> bool:
        """True when the plan was refused before any command was sent."""
        return (
            self.safety_report is not None
            and not self.safety_report.ok
            and not self.step_results
        )


class Executor:
    """
    Executes an ActionPlan on a robot instance step by step.

    Args:
        robot:          A MockRobot (or real robot with the same interface)
        tracker:        Optional PipelineTracker for cross-domain logging
        task_id:        Optional task_id for tracker
        safety_limits:  WorkspaceLimits to validate the plan against before any
                        motion. None disables the pre-flight check.
        emergency_stop: Optional EmergencyStop checked before every command.
    """

    def __init__(
        self,
        robot: MockRobot,
        tracker=None,
        task_id: Optional[str] = None,
        timeout_seconds: float = 5.0,
        safety_limits: Optional[WorkspaceLimits] = None,
        emergency_stop: Optional[EmergencyStop] = None,
    ):
        self.robot   = robot
        self.tracker = tracker
        self.task_id = task_id
        self.timeout_seconds = timeout_seconds
        self.safety_limits   = safety_limits
        self.emergency_stop  = emergency_stop

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

        # ── Pre-flight safety gate (S6-9) ─────────────────────────────────────
        # Runs before anything is sent to the robot. A plan with an unsafe
        # target is refused whole, so the arm is never left holding a block
        # half-way through a sequence it was always going to fail.
        safety_report = None
        if self.safety_limits is not None:
            safety_report = validate_plan(plan, self.safety_limits)
            if verbose:
                print(safety_report.summary())
            if self.tracker and self.task_id:
                self.tracker.record(
                    self.task_id,
                    "safety_check",
                    status="success" if safety_report.ok else "failed",
                    payload={
                        "positions_checked": safety_report.positions_checked,
                        "violations": [str(v) for v in safety_report.violations],
                    },
                    error=None if safety_report.ok else str(safety_report.violations[0]),
                )
            if not safety_report.ok:
                reason = (
                    f"Blocked by the pre-execution safety check: "
                    f"{safety_report.violations[0]}"
                )
                if verbose:
                    print("\n  ✗ Execution refused - no motion was started.\n")
                return ExecutionResult(
                    plan=plan,
                    step_results=[],
                    success=False,
                    failed_step=safety_report.violations[0].step,
                    failed_reason=reason,
                    total_latency_ms=0.0,
                    safety_report=safety_report,
                )

        if verbose:
            print("Executing plan...\n")

        step_results = []
        total_start  = time.perf_counter()

        for cmd in plan.commands:
            # ── Emergency stop checked at every command boundary (S6-9) ───────
            if self.emergency_stop is not None and self.emergency_stop.triggered:
                total_ms = (time.perf_counter() - total_start) * 1000
                reason = (f"Emergency stop before step {cmd.step}: "
                          f"{self.emergency_stop.reason}")
                logger.critical("[executor] %s", reason)
                if self.tracker and self.task_id:
                    self.tracker.record(
                        self.task_id, "execution", status="failed", error=reason,
                    )
                if verbose:
                    print(f"\n  ■ {reason}\n")
                return ExecutionResult(
                    plan=plan,
                    step_results=step_results,
                    success=False,
                    failed_step=cmd.step,
                    failed_reason=reason,
                    total_latency_ms=total_ms,
                    safety_report=safety_report,
                    stopped=True,
                )

            if verbose:
                print(f"  Step {cmd.step}: {cmd.command_type.value.upper()} "
                      f"{'«' + cmd.target_object + '»' if cmd.target_object else ''}", end=" ", flush=True)

            step_start = time.perf_counter()

            result = self._execute_command(cmd)

            step_elapsed = time.perf_counter() - step_start

            if step_elapsed > self.timeout_seconds:
                result.success = False
                result.message = (
                    f"Execution timeout exceeded "
                    f"({step_elapsed:.2f}s > {self.timeout_seconds}s)"
                )
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
                    safety_report=safety_report,
                )

        total_ms = (time.perf_counter() - total_start) * 1000

        if verbose:
            print(f"\n  ✓ Plan completed successfully in {total_ms:.0f}ms\n")

        return ExecutionResult(
            plan=plan,
            step_results=step_results,
            success=True,
            total_latency_ms=total_ms,
            safety_report=safety_report,
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
        if results.safety_report is not None:
            verdict = "✓ PASS" if results.safety_report.ok else "✗ BLOCKED"
            print(f"  Safety check:    {verdict} "
                  f"({results.safety_report.positions_checked} positions validated)")
        if results.stopped:
            print("  Emergency stop:  ■ plan halted at a command boundary")
        if results.failed_step:
            print(f"  Failed at step:  {results.failed_step}")
            print(f"  Reason:          {results.failed_reason}")
        print(f"{'═'*55}\n")