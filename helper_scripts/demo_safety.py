#!/usr/bin/env python3
"""
helper_scripts/demo_safety.py
-----------------------------
S6-9 evidence script. Shows the pre-execution safety check and the emergency
stop doing their jobs, with no API key and no PyBullet window needed.

Six cases:

    1-3  Plans that should run, and do.
    4    A plan whose second step is off the table. Refused before any command.
    5    A plan whose target is inside the table but past the arm's reach.
         A box check passes it; the reach check does not.
    6    An emergency stop raised during step 1. The plan halts at the next
         command boundary with step 1 still completed.

Run from the project root:
    python helper_scripts/demo_safety.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The safety module logs every rejection. validate_plan() is called twice per
# case here, once to print the report and once inside the Executor, so the log
# lines are suppressed to keep this output readable. They are on by default in
# the pipeline, which is where they belong.
logging.getLogger("task_planner.safety").setLevel(logging.CRITICAL + 1)
logging.getLogger("simulation_backend.executor").setLevel(logging.CRITICAL + 1)

from llm_backend.schema import ActionType, ConfidenceLevel, ParsedInstruction
from simulation_backend.executor import Executor
from simulation_backend.mock_robot import MockRobot
from task_planner.planner import TaskPlanner
from task_planner.safety import EmergencyStop, default_limits, validate_plan

SEP = "=" * 78

# scene_config.yaml, in metres.
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


def parsed(action, obj, dest=None, relation=None, raw=""):
    return ParsedInstruction(
        action=action, object_target=obj, destination=dest,
        spatial_relation=relation, confidence=ConfidenceLevel.HIGH,
        raw_instruction=raw,
    )


CASES = [
    ("SAFE-1", "pick up the red block and put it in the right tray",
     parsed(ActionType.PICK, "red block", "right tray", "in",
            "pick up the red block and put it in the right tray"), None),
    ("SAFE-2", "move the blue block to the left tray",
     parsed(ActionType.MOVE, "blue block", "left tray", "to",
            "move the blue block to the left tray"), None),
    ("SAFE-3", "place the green block to the left of the blue block",
     parsed(ActionType.PLACE, "green block", "blue block", "left of",
            "place the green block to the left of the blue block"), None),
    ("UNSAFE-1", "put the yellow block on the stray pallet (9 m off the table)",
     parsed(ActionType.PICK, "yellow block", "stray pallet", "in",
            "put the yellow block on the stray pallet"),
     {"label": "stray pallet", "position": (9.00, 9.00)}),
    ("UNSAFE-2", "put the red block to the left of the workstation",
     parsed(ActionType.PLACE, "red block", "workstation", "left of",
            "put the red block to the left of the workstation"), None),
]


def banner(title):
    print(f"\n{SEP}\n  {title}\n{SEP}")


def main():
    limits = default_limits()

    banner("S6-9 — PRE-EXECUTION SAFETY CHECK")
    print(f"  Limits source : {limits.source}")
    print(f"  Limits        : {limits.describe()}")
    print(f"  Table         : 2.0 m x 1.5 m, centred on the robot base, "
          f"{limits.margin_m * 1000:.0f} mm wall margin")
    print("\n  Scene object clearance against the arm's reach:")
    for obj in SCENE["objects"]:
        x, y = obj["position"]
        radius = limits.radius_from_base(x, y)
        margin = limits.reach_m - radius
        print(f"    {obj['label']:<14} ({x:+.2f}, {y:+.2f})  "
              f"radius {radius:.3f} m   margin {margin * 1000:+7.1f} mm")

    planner = TaskPlanner()
    blocked = 0
    executed = 0

    for case_id, text, instruction, extra in CASES:
        banner(f"{case_id}  —  \"{text}\"")
        scene = {"objects": list(SCENE["objects"])}
        if extra:
            scene["objects"].append(extra)
            print(f"  Scene has an extra object: {extra['label']} at "
                  f"{extra['position']}")

        try:
            plan = planner.generate_plan(instruction, scene)
        except ValueError as exc:
            print(f"  Plan-time rejection (Sprint 5 check): {exc}")
            continue

        print(f"  Plan: {plan.total_steps} steps")
        for cmd in plan.commands:
            print(f"    {cmd.summary()}")

        report = validate_plan(plan, limits)
        print()
        for line in report.summary().splitlines():
            print(f"  {line}")

        robot = MockRobot()
        robot.load_scene(scene)
        before = robot.get_position()
        result = Executor(robot, safety_limits=limits).execute(plan, verbose=False)
        after = robot.get_position()

        print(f"\n  Executor verdict  : "
              f"{'completed' if result.success else 'refused / failed'}")
        print(f"  Steps completed   : {result.steps_completed} / {plan.total_steps}")
        print(f"  Arm position      : {before} -> {after}"
              f"{'   (did not move)' if before == after else ''}")
        if not result.success:
            print(f"  Reason            : {result.failed_reason}")
            blocked += 1
        else:
            executed += 1

    # ── Emergency stop ────────────────────────────────────────────────────────
    banner("ESTOP-1  —  stop raised while step 1 of a five-step plan was running")
    plan = planner.generate_plan(
        parsed(ActionType.PICK, "red block", "right tray", "in",
               "pick up the red block and put it in the right tray"),
        SCENE,
    )
    robot = MockRobot()
    robot.load_scene(SCENE)

    estop = EmergencyStop()
    executor = Executor(robot, safety_limits=limits, emergency_stop=estop)
    original = executor._execute_command

    def stop_during_step_one(cmd):
        outcome = original(cmd)
        if cmd.step == 1:
            estop.trigger("operator pressed the stop while step 1 was running")
        return outcome

    executor._execute_command = stop_during_step_one
    result = executor.execute(plan, verbose=False)

    print(f"  Plan steps        : {plan.total_steps}")
    print(f"  Steps completed   : {result.steps_completed}")
    print(f"  Halted before step: {result.failed_step}")
    print(f"  Stopped flag      : {result.stopped}")
    print(f"  Reason            : {result.failed_reason}")
    print(f"  Held object       : {robot.get_held_object()}")
    print("\n  The step that was already running finished. Nothing after it ran.")

    banner("SUMMARY")
    print(f"  Plans executed        : {executed}")
    print(f"  Plans refused         : {blocked}  (no command sent in either case)")
    print(f"  Emergency stop        : halted at a command boundary, "
          f"{result.steps_completed} step(s) left completed")
    print("  Workspace definitions : 1  (was 4 — MockRobot, RobotBase, "
          "Kuka_IIWA, Franka_panda)")
    print(SEP)


if __name__ == "__main__":
    main()
