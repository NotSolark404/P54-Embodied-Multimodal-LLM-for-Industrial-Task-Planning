"""
main.py
-------
Wires all modules together:
    User instruction
        → LLM parse          (llm_backend/custom_LLM_parser.py)
        → Vision lookup      (vision_backend/scene_representation.py  OR
                              simulation_backend/simulation.py)
        → Task plan          (task_planner/planner.py)
        → Execution          (simulation_backend/executor.py)
        → Feedback           (inline validation)

All stages are logged via tracker.py with a unique task_id.
LLM backend is controlled by LLM_BACKEND in .env — not a CLI flag.

Vision source is controlled by USE_LIVE_SIMULATION in .env:
    USE_LIVE_SIMULATION=false  (default) — reads JSON from disk
    USE_LIVE_SIMULATION=true             — uses live PyBullet simulation

Usage:
    # Single instruction (JSON fallback)
    python main.py "pick up the red block and place it in the left tray"

    # Single instruction (live simulation)
    USE_LIVE_SIMULATION=true python main.py "pick up the red block"

    # Interactive mode
    python main.py --interactive

    # Suppress output
    python main.py --quiet "locate the yellow block"
"""
import os
import sys
import argparse
import logging
import time
import logging
logger = logging.getLogger(__name__)

os.environ["PYDANTIC_DISABLE_PLUGINS"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

# ── Module imports ─────────────────────────────────────────────────────────────
from llm_backend.custom_LLM_parser import parse_instruction
from llm_backend.schema            import ParsedInstruction, ConfidenceLevel
from llm_backend.tracker           import PipelineTracker
from task_planner.planner          import TaskPlanner
from vision_backend.scene_representation import get_current_scene
from simulation_backend.mock_robot import MockRobot
from simulation_backend.executor   import Executor
from simulation_backend.action_schema import plan_to_commands
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
)

SEP = "═" * 60

# ── Live simulation flag ───────────────────────────────────────────────────────
_USE_LIVE = os.getenv("USE_LIVE_SIMULATION", "false").strip().lower() == "true"


def _get_scene_and_robot(sim=None, verbose: bool = True):
    """
    Return (scene_dict, robot_instance) from either live simulation or JSON.

    If USE_LIVE_SIMULATION=true and a Simulation instance is provided,
    calls sim.get_live_scene(verbose) which prints the detection table
    inline inside Stage 2 when verbose=True.

    Otherwise falls back to the existing JSON-based get_current_scene()
    and a fresh MockRobot.

    Args:
        sim     : Simulation instance (or None for JSON mode).
        verbose : Whether to print the detection summary table.

    Returns:
        (scene dict, robot instance)
    """
    if _USE_LIVE and sim is not None:
        scene = sim.get_live_scene(verbose=verbose)
        robot = sim.get_robot()
    else:
        scene = get_current_scene()
        robot = MockRobot()
    return scene, robot


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline(
    instruction: str,
    verbose:     bool = True,
    tracker:     PipelineTracker | None = None,
    sim=None,
) -> dict:
    """
    Run the full pipeline for a single instruction.

    Args:
        instruction : Natural language task instruction.
        verbose     : Print progress to stdout.
        tracker     : PipelineTracker instance for cross-domain logging.
        sim         : Simulation instance (required for live mode).
                      Pass None to use JSON scene fallback.

    Returns:
        Result dict — keys: success, task_id, parsed, plan, execution.
    """
    if tracker is None:
        tracker = PipelineTracker()

    _backend = os.getenv("LLM_BACKEND", "openai")

    # ── Register task ──────────────────────────────────────────────────────────
    task_id = tracker.new_task(instruction, model=_backend)

    vision_label = "Live Simulation" if (_USE_LIVE and sim) else "JSON file"

    if verbose:
        print(f"\n{SEP}")
        print(f"  PIPELINE START")
        print(f"  Instruction : {instruction}")
        print(f"  Model       : {_backend}")
        print(f"  Vision      : {vision_label}")
        print(f"  Task ID     : {task_id}")
        print(SEP)

    result = {
        "success":   False,
        "task_id":   task_id,
        "parsed":    None,
        "plan":      None,
        "execution": None,
    }

    # ══ STAGE 1: LLM PARSE ════════════════════════════════════════════════════
    if verbose:
        print(f"\n  [1/5] LLM Parse ({_backend})")

    try:
        t0     = time.perf_counter()
        parsed = parse_instruction(instruction)
        lat    = (time.perf_counter() - t0) * 1000

        result["parsed"] = parsed

        tracker.record(
            task_id, "llm_parse", status="success",
            payload=parsed.model_dump(mode="json"),
            latency_ms=lat,
        )

        if verbose:
            print(f"       Action      : {parsed.action.value}")
            print(f"       Object      : {parsed.object_target}")
            print(f"       Destination : {parsed.destination or '—'}")
            print(f"       Spatial     : {parsed.spatial_relation or '—'}")
            print(f"       Confidence  : {parsed.confidence.value}")
            print(f"       Latency     : {lat:.0f}ms")

        if parsed.confidence == ConfidenceLevel.LOW:
            if verbose:
                print(f"\n  ⚠  Low confidence — instruction may be ambiguous")
                print(f"     Notes: {parsed.notes}")
            tracker.record(task_id, "feedback", status="retry",
                           payload={"reason": "low_confidence", "notes": parsed.notes})
            result["success"] = False
            tracker.complete_task(task_id, success=False)
            return result

    except Exception as e:
        tracker.record(task_id, "llm_parse", status="failed", error=str(e))
        tracker.complete_task(task_id, success=False)
        if verbose:
            print(f"       ✗ LLM parse failed: {e}")
        return result

    # ══ STAGE 2: VISION LOOKUP ════════════════════════════════════════════════
    if verbose:
        print(f"\n  [2/5] Vision Lookup  [{vision_label}]")

    try:
        t0 = time.perf_counter()
        scene, robot = _get_scene_and_robot(sim, verbose=verbose)
        lat = (time.perf_counter() - t0) * 1000
        objects = scene.get("objects", [])

        if not objects:
            message = (
                "No objects detected in the current scene. "
                "Check the vision scene file or simulation before planning."
            )
            print(f"       ⚠ {message}")

        tracker.record(
            task_id, "vision_lookup", status="success",
            payload={
                "object_count": len(objects),
                "objects": [o.get("label") for o in objects],
                "source": vision_label,
            },
            latency_ms=lat,
        )
        
        if verbose:
            print(f"       Objects in scene: {[o.get('label') for o in objects]}")
            print(f"       Latency         : {lat:.0f}ms")

    except FileNotFoundError as e:
        message = f"Scene file missing: {e}"
        tracker.record(task_id, "vision_lookup", status="failed", error=message)
        tracker.complete_task(task_id, success=False)
        tracker.save()
        if verbose:
            print(f"       ✗ Vision lookup failed: {message}")
        return result

    except Exception as e:
        tracker.record(task_id, "vision_lookup", status="failed", error=str(e))
        tracker.complete_task(task_id, success=False)
        tracker.save()
        if verbose:
            print(f"       ✗ Vision lookup failed: {e}")
        return result

    # ══ STAGE 3: TASK PLANNING ════════════════════════════════════════════════
    if verbose:
        print(f"\n  [3/5] Task Planning")

    try:
        planner = TaskPlanner()
        t0      = time.perf_counter()
        plan    = planner.generate_plan(parsed, scene, task_id=task_id)
        lat     = (time.perf_counter() - t0) * 1000

        result["plan"] = plan

        tracker.record(
            task_id, "task_plan", status="success",
            payload={
                "steps":    plan.total_steps,
                "commands": [c.command_type.value for c in plan.commands],
            },
            latency_ms=lat,
        )
        if verbose:
            print(f"       Steps generated : {plan.total_steps}")
            for cmd in plan.commands:
                print(f"       {cmd.summary()}")

    except ValueError as e:
        tracker.record(task_id, "task_plan", status="failed", error=str(e))
        tracker.complete_task(task_id, success=False)
        if verbose:
            print(f"       ✗ Planning failed: {e}")
        return result

    # ══ STAGE 4: EXECUTION ════════════════════════════════════════════════════
    robot_label = type(robot).__name__
    if verbose:
        print(f"\n  [4/5] Execution  [{robot_label}]")

    try:
        robot.load_scene(scene)
        executor = Executor(robot, tracker=tracker, task_id=task_id)
        exec_res = executor.execute(plan, verbose=verbose)

        result["execution"] = exec_res

        if not exec_res.success:
            tracker.complete_task(task_id, success=False)
            result["success"] = False
            return result

    except Exception as e:
        tracker.record(task_id, "execution", status="failed", error=str(e))
        tracker.complete_task(task_id, success=False)
        if verbose:
            print(f"       ✗ Execution error: {e}")
        return result

    # ══ STAGE 5: FEEDBACK ════════════════════════════════════════════════════
    if verbose:
        print(f"  [5/5] Feedback & Validation")

    tracker.record(
        task_id, "feedback", status="success",
        payload={
            "steps_completed": exec_res.steps_completed,
            "total_steps":     plan.total_steps,
            "latency_ms":      exec_res.total_latency_ms,
        },
    )
    tracker.complete_task(task_id, success=True)
    result["success"] = True

    if verbose:
        print(f"       ✓ Task completed — {exec_res.steps_completed}/{plan.total_steps} steps")
        print(f"\n{SEP}")
        print(f"  PIPELINE COMPLETE  ✓  Task ID: {task_id}")
        print(SEP)
        tracker.print_task(task_id)

    tracker.save()
    return result


# ── Interactive mode ───────────────────────────────────────────────────────────

def run_interactive(sim=None) -> None:
    tracker  = PipelineTracker()
    _backend = os.getenv("LLM_BACKEND", "openai")
    vision_label = "Live Simulation" if (_USE_LIVE and sim) else "JSON file"

    print(f"\n{SEP}")
    print("  Multimodal LLM — Industrial Task Planning Pipeline")
    print(f"  Model: {_backend}  |  Vision: {vision_label}")
    print("  Type 'quit' to exit  |  'status' for summary  |  'reset' to reset scene")
    print(SEP + "\n")

    while True:
        try:
            instruction = input("Instruction: ").strip()
            if not instruction:
                continue
            if instruction.lower() in ("quit", "exit", "q"):
                tracker.print_summary()
                print("Goodbye!")
                break
            if instruction.lower() == "status":
                tracker.print_summary()
                continue
            if instruction.lower() == "reset" and sim is not None:
                sim.reset()
                print("  Scene reset to initial positions.\n")
                continue
            run_pipeline(instruction, verbose=True, tracker=tracker, sim=sim)

        except KeyboardInterrupt:
            print("\nGoodbye!")
            tracker.print_summary()
            break
        except Exception as e:
            print(f"  ✗ Pipeline error: {e}")

robot_type = os.getenv("ROBOT_BACKEND", "mock").lower()

if robot_type == "ros":
    from simulation_backend.robots.ros_robot import ROSRobot
    robot = ROSRobot()
    logger.info("Using ROS2 robot")
elif robot_type == "real":
    from simulation_backend.robots.kuka_robot import KukaRobot
    robot = KukaRobot()
else:
    from simulation_backend.mock_robot import MockRobot
    robot = MockRobot()


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Multimodal LLM Industrial Task Planning Pipeline"
    )
    ap.add_argument("instruction", nargs="?", help="Instruction to execute")
    ap.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    ap.add_argument("--quiet",       "-q", action="store_true", help="Suppress verbose output")
    ap.add_argument("--live",        "-l", action="store_true",
                    help="Force live simulation (overrides USE_LIVE_SIMULATION env var)")
    args = ap.parse_args()

    # --live flag overrides the env var
    if args.live:
        os.environ["USE_LIVE_SIMULATION"] = "true"
        _USE_LIVE = True  # noqa: F811

    # Start simulation if live mode is requested
    sim = None
    if _USE_LIVE:
        try:
            from simulation_backend.simulation import Simulation
            sim = Simulation()
            print(f"  Simulation started — {len(sim.registry)} objects loaded.")
        except Exception as e:
            print(f"  ✗ Failed to start simulation: {e}")
            print("  Falling back to JSON scene.")
            sim = None

    try:
        if args.interactive:
            run_interactive(sim=sim)
        elif args.instruction:
            run_pipeline(args.instruction, verbose=not args.quiet, sim=sim)
        else:
            ap.print_help()
    finally:
        if sim is not None:
            sim.disconnect()
