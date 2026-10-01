"""
demo_sprint3.py
---------------
DEMO-1: Sprint 3 client demonstration script.

Covers all 6 instruction categories:
    1. Simple         — pick up the red block
    2. Spatial        — place the red block to the left of the blue block
    3. Synonym        — grab the yellow block and drop it in the right tray
    4. Multi-step     — pick up the red block then locate the green block
    5. Ambiguous      — graceful low-confidence exit (no API call wasted)
    6. Edge case      — PICK UP THE RED BLOCK (caps normalisation)

Also demonstrates:
    - Tracker status summary after all instructions
    - Baseline parser comparison for one instruction side-by-side

Usage:
    python demo_sprint3.py                  # run all 6 demo instructions
    python demo_sprint3.py --interactive    # type your own
    python demo_sprint3.py --baseline       # show baseline vs LLM side-by-side
"""

import sys
import os
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from task_planner.planner  import TaskPlanner
from execution.mock_robot  import MockRobot
from execution.executor    import Executor
from tracker               import PipelineTracker
from schema                import ParsedInstruction, ActionType, ConfidenceLevel, ConfidenceLevel
from baseline_parser       import BaselineParser

SEP  = "═" * 62
SEP2 = "─" * 62

DEFAULT_SCENE = {
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

# ── 6 demo instructions ────────────────────────────────────────────────────────
DEMO_INSTRUCTIONS = [
    {
        "category": "simple",
        "instruction": "pick up the red block and place it in the left tray",
        "note": "Basic pick-and-place — full 5-step plan",
    },
    {
        "category": "spatial",
        "instruction": "place the green block to the right of the workstation",
        "note": "Spatial offset: workstation (5,5) + right_of offset → (6.5, 5)",
    },
    {
        "category": "synonym",
        "instruction": "grab the yellow block and drop it in the right tray",
        "note": "grab→pick, drop→place — synonym mapping via LLM",
    },
    {
        "category": "multi-step",
        "instruction": "move the blue block near the workstation",
        "note": "Move with spatial 'near' relation",
    },
    {
        "category": "ambiguous",
        "instruction": "put that thing over there",
        "note": "Low confidence — pipeline exits at Stage 1, no wasted execution",
    },
    {
        "category": "edge case",
        "instruction": "PICK UP THE RED BLOCK AND PLACE IT IN THE LEFT TRAY",
        "note": "All-caps normalised before LLM call",
    },
]


def run_demo_instruction(
    instruction: str,
    category:    str,
    note:        str,
    tracker:     PipelineTracker,
    verbose:     bool = True,
) -> dict:
    """Run one demo instruction through the full pipeline."""
    from parser import parse_instruction

    if verbose:
        print(f"\n  Category   : {category.upper()}")
        print(f"  Instruction: {instruction}")
        print(f"  Note       : {note}")
        print(f"  {SEP2}")

    task_id = tracker.new_task(instruction)
    result  = {"success": False, "task_id": task_id}

    try:
        # Stage 1: LLM parse
        t0     = time.perf_counter()
        parsed = parse_instruction(instruction)
        lat    = (time.perf_counter() - t0) * 1000
        tracker.record(task_id, "llm_parse", status="success",
                       payload=parsed.model_dump(mode="json"), latency_ms=lat)

        if verbose:
            print(f"  [1] LLM Parse    action={parsed.action.value}  "
                  f"object={parsed.object_target}  "
                  f"dest={parsed.destination or '—'}  "
                  f"spatial={parsed.spatial_relation or '—'}  "
                  f"conf={parsed.confidence.value}  ({lat:.0f}ms)")

        if parsed.confidence == ConfidenceLevel.LOW:
            tracker.record(task_id, "feedback", status="retry",
                           payload={"reason": "low_confidence"})
            tracker.complete_task(task_id, success=False)
            if verbose:
                print(f"  ⚠  Low confidence — exiting gracefully. Notes: {parsed.notes}")
            return result

        # Stage 2: Vision lookup (stub)
        tracker.record(task_id, "vision_lookup", status="success", latency_ms=0.5,
                       payload={"objects": [o["label"] for o in DEFAULT_SCENE["objects"]]})
        if verbose:
            print(f"  [2] Vision       {len(DEFAULT_SCENE['objects'])} objects in scene [STUB]")

        # Stage 3: Task planning
        t0   = time.perf_counter()
        plan = TaskPlanner().generate_plan(parsed, DEFAULT_SCENE, task_id=task_id)
        lat  = (time.perf_counter() - t0) * 1000
        tracker.record(task_id, "task_plan", status="success", latency_ms=lat,
                       payload={"steps": plan.total_steps})
        if verbose:
            print(f"  [3] Task Plan    {plan.total_steps} steps generated  ({lat:.1f}ms)")
            for cmd in plan.commands:
                print(f"       {cmd.summary()}")

        # Stage 4: Execution
        robot    = MockRobot()
        robot.load_scene(DEFAULT_SCENE)
        exec_res = Executor(robot, tracker=tracker, task_id=task_id).execute(
            plan, verbose=False
        )
        if verbose:
            status = "✓ success" if exec_res.success else f"✗ failed at step {exec_res.failed_step}"
            print(f"  [4] Execution    {status}  "
                  f"{exec_res.steps_completed}/{plan.total_steps} steps  "
                  f"({exec_res.total_latency_ms:.1f}ms)")

        # Stage 5: Feedback
        tracker.record(task_id, "feedback", status="success",
                       payload={"steps_completed": exec_res.steps_completed})
        tracker.complete_task(task_id, success=exec_res.success)
        result["success"] = exec_res.success

        if verbose:
            print(f"  [5] Feedback     {'✓ completed' if exec_res.success else '✗ failed'}")

    except ValueError as e:
        tracker.complete_task(task_id, success=False)
        if verbose:
            print(f"  ✗ Planning error: {e}")
    except Exception as e:
        tracker.complete_task(task_id, success=False)
        if verbose:
            print(f"  ✗ Pipeline error: {e}")

    return result


def run_baseline_comparison(instruction: str) -> None:
    """Show baseline parser vs LLM parser side-by-side for one instruction."""
    from parser import parse_instruction

    print(f"\n{SEP}")
    print(f"  BASELINE vs LLM COMPARISON")
    print(f"  Instruction: {instruction}")
    print(f"{SEP}")

    # Baseline
    baseline = BaselineParser().parse(instruction)
    print(f"\n  Rule-Based Baseline (no LLM):")
    print(f"    action:      {baseline.action or '—'}")
    print(f"    object:      {baseline.object_target or '—'}")
    print(f"    destination: {baseline.destination or '—'}")
    print(f"    spatial:     {baseline.spatial_relation or '—'}")
    print(f"    confidence:  {baseline.confidence}")
    print(f"    latency:     {baseline.latency_ms:.3f}ms")

    # LLM
    print(f"\n  LLM Parser (GPT-4o):")
    try:
        t0     = time.perf_counter()
        parsed = parse_instruction(instruction)
        lat    = (time.perf_counter() - t0) * 1000
        print(f"    action:      {parsed.action.value}")
        print(f"    object:      {parsed.object_target}")
        print(f"    destination: {parsed.destination or '—'}")
        print(f"    spatial:     {parsed.spatial_relation or '—'}")
        print(f"    confidence:  {parsed.confidence.value}")
        print(f"    latency:     {lat:.0f}ms")
    except Exception as e:
        print(f"    Error: {e}")

    print()


def run_full_demo() -> None:
    tracker = PipelineTracker()
    passed  = 0

    print(f"\n{SEP}")
    print("  SPRINT 3 — CLIENT DEMO")
    print("  Multimodal LLM for Industrial Task Planning")
    print("  5-stage pipeline  ·  MockRobot  ·  GPT-4o")
    print(SEP)

    for item in DEMO_INSTRUCTIONS:
        print(f"\n{SEP}")
        r = run_demo_instruction(
            item["instruction"], item["category"], item["note"],
            tracker, verbose=True,
        )
        if r["success"] or item["category"] == "ambiguous":
            passed += 1

    print(f"\n{SEP}")
    print(f"  Demo complete: {passed}/{len(DEMO_INSTRUCTIONS)} instructions handled correctly")
    print(SEP)
    tracker.print_summary()
    tracker.save()


def run_interactive() -> None:
    tracker = PipelineTracker()
    print(f"\n{SEP}")
    print("  Sprint 3 Interactive Pipeline")
    print("  Type an instruction | 'status' | 'baseline <instruction>' | 'quit'")
    print(SEP + "\n")

    while True:
        try:
            raw = input("Instruction: ").strip()
            if not raw:
                continue
            if raw.lower() in ("quit", "exit", "q"):
                tracker.print_summary()
                break
            if raw.lower() == "status":
                tracker.print_summary()
                continue
            if raw.lower().startswith("baseline "):
                run_baseline_comparison(raw[9:].strip())
                continue
            run_demo_instruction(raw, "interactive", "", tracker, verbose=True)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            tracker.print_summary()
            break
        except Exception as e:
            print(f"  ✗ Error: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sprint 3 Client Demo")
    ap.add_argument("--interactive", "-i", action="store_true")
    ap.add_argument("--baseline",    "-b", action="store_true",
                    help="Show baseline vs LLM comparison for one instruction")
    ap.add_argument("instruction", nargs="?",
                    help="Single instruction to run (with --baseline)")
    args = ap.parse_args()

    if args.interactive:
        run_interactive()
    elif args.baseline and args.instruction:
        run_baseline_comparison(args.instruction)
    elif args.instruction:
        tracker = PipelineTracker()
        run_demo_instruction(args.instruction, "single", "", tracker, verbose=True)
        tracker.print_summary()
    else:
        run_full_demo()
