"""
tracker.py
----------
Cross-domain pipeline tracker for the Multimodal LLM Industrial Task Planning system.

Assigns a unique task_id to every instruction and records what happens at
each pipeline stage:
    1. llm_parse        - LLM parse stage (this module)
    2. vision_lookup    - Vision module scene lookup
    3. task_plan        - Task planning module
    4. execution        - Execution module
    5. feedback         - Validation and feedback

Each stage records: timestamp, status, output payload, latency, and any errors.
All events are written to a rolling task_log.json for audit and debugging.

Usage:
    from llm_backend.tracker import PipelineTracker

    tracker = PipelineTracker()
    task_id = tracker.new_task("pick up the red block")

    tracker.record(task_id, "llm_parse",     status="success", payload=result.model_dump())
    tracker.record(task_id, "vision_lookup", status="success", payload=scene_data)
    tracker.record(task_id, "task_plan",     status="success", payload=action_plan)
    tracker.record(task_id, "execution",     status="failed",  error="Object not found")
    tracker.record(task_id, "feedback",      status="retry",   payload={"retry_count": 1})

    tracker.print_task(task_id)
    tracker.save()
"""

import uuid
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Stage definitions ──────────────────────────────────────────────────────────
PIPELINE_STAGES = [
    "llm_parse",
    "vision_lookup",
    "task_plan",
    "execution",
    "feedback",
]

STAGE_LABELS = {
    "llm_parse":     "LLM Instruction Parser",
    "vision_lookup": "Vision Module / Scene Lookup",
    "task_plan":     "Task Planning Module",
    "execution":     "Execution Module",
    "feedback":      "Validation & Feedback",
}

STATUS_SYMBOLS = {
    "success": "✓",
    "failed":  "✗",
    "retry":   "↺",
    "skipped": "○",
    "pending": "…",
}


class PipelineTracker:
    """
    Tracks the lifecycle of a task through all pipeline stages.
    Thread-safe for single-process use. Not concurrent.
    """

    def __init__(self, log_path: str = "task_log.json"):
        self.log_path = Path(log_path)
        self._tasks: dict[str, dict] = {}
        self._load_existing()

    # ── Public API ────────────────────────────────────────────────────────────

    def new_task(self, instruction: str, model: Optional[str] = None) -> str:
        """
        Register a new task and return its unique task_id.

        Args:
            instruction: The raw natural language instruction.
            model:       The LLM model being used (optional).

        Returns:
            task_id: A UUID string that identifies this task across all stages.
        """
        task_id = str(uuid.uuid4())[:8]  # short 8-char ID for readability
        self._tasks[task_id] = {
            "task_id":    task_id,
            "instruction": instruction,
            "model":      model,
            "created_at": self._now(),
            "status":     "in_progress",
            "stages":     {},
        }
        logger.debug(f"New task registered: {task_id} — '{instruction}'")
        return task_id

    def record(
        self,
        task_id: str,
        stage: str,
        status: str,
        payload: Optional[Any] = None,
        error: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> None:
        """
        Record the outcome of a pipeline stage for a given task.

        Args:
            task_id:    The task ID returned by new_task().
            stage:      One of PIPELINE_STAGES.
            status:     "success", "failed", "retry", "skipped".
            payload:    Any serialisable output from the stage (dict, list, str).
            error:      Error message if status is "failed".
            latency_ms: Time taken by this stage in milliseconds.
        """
        if task_id not in self._tasks:
            logger.warning(f"Task ID '{task_id}' not found. Call new_task() first.")
            return

        if stage not in PIPELINE_STAGES:
            logger.warning(f"Unknown stage '{stage}'. Valid stages: {PIPELINE_STAGES}")

        self._tasks[task_id]["stages"][stage] = {
            "stage":      stage,
            "status":     status,
            "timestamp":  self._now(),
            "latency_ms": round(latency_ms, 1) if latency_ms else None,
            "payload":    self._serialise(payload),
            "error":      error,
        }

        # Update overall task status
        if status == "failed":
            self._tasks[task_id]["status"] = "failed"
        elif status == "success" and stage == PIPELINE_STAGES[-1]:
            self._tasks[task_id]["status"] = "completed"

        logger.debug(f"Stage recorded: [{task_id}] {stage} → {status}")

    def complete_task(self, task_id: str, success: bool) -> None:
        """Mark a task as completed or failed after all stages."""
        if task_id not in self._tasks:
            return
        self._tasks[task_id]["status"] = "completed" if success else "failed"
        self._tasks[task_id]["completed_at"] = self._now()

    def get_task(self, task_id: str) -> Optional[dict]:
        """Return the full task record for a given task_id."""
        return self._tasks.get(task_id)

    def get_all_tasks(self) -> list[dict]:
        """Return all tracked tasks sorted by creation time."""
        return sorted(self._tasks.values(), key=lambda t: t["created_at"])

    def print_task(self, task_id: str) -> None:
        """Pretty-print a single task trace to stdout."""
        task = self._tasks.get(task_id)
        if not task:
            print(f"Task '{task_id}' not found.")
            return

        print(f"\n{'─'*60}")
        print(f"  Task ID:     {task['task_id']}")
        print(f"  Instruction: {task['instruction']}")
        if task.get("model"):
            print(f"  Model:       {task['model']}")
        print(f"  Status:      {task['status'].upper()}")
        print(f"  Created:     {task['created_at']}")
        print(f"{'─'*60}")

        for stage_name in PIPELINE_STAGES:
            stage = task["stages"].get(stage_name)
            label = STAGE_LABELS.get(stage_name, stage_name)

            if stage is None:
                print(f"  {STATUS_SYMBOLS['pending']}  {label:<35} (not reached)")
                continue

            sym = STATUS_SYMBOLS.get(stage["status"], "?")
            latency = f"{stage['latency_ms']:.0f}ms" if stage["latency_ms"] else "—"
            print(f"  {sym}  {label:<35} [{stage['status']:<7}] {latency:>8}")

            if stage.get("error"):
                print(f"       Error: {stage['error']}")

        print(f"{'─'*60}\n")

    def print_summary(self) -> None:
        """Print a summary of all tracked tasks."""
        tasks = self.get_all_tasks()
        if not tasks:
            print("No tasks tracked yet.")
            return

        total     = len(tasks)
        completed = sum(t["status"] == "completed" for t in tasks)
        failed    = sum(t["status"] == "failed" for t in tasks)
        in_prog   = total - completed - failed

        print(f"\n{'PIPELINE TRACKER SUMMARY':^60}")
        print("─" * 60)
        print(f"  Total tasks:      {total}")
        print(f"  Completed:        {completed}")
        print(f"  Failed:           {failed}")
        print(f"  In progress:      {in_prog}")
        print("─" * 60)

        # Stage failure breakdown
        stage_failures: dict[str, int] = {s: 0 for s in PIPELINE_STAGES}
        for t in tasks:
            for stage_name, stage in t["stages"].items():
                if stage["status"] == "failed":
                    stage_failures[stage_name] = stage_failures.get(stage_name, 0) + 1

        print("  Failures by stage:")
        for stage_name in PIPELINE_STAGES:
            count = stage_failures.get(stage_name, 0)
            if count > 0:
                label = STAGE_LABELS.get(stage_name, stage_name)
                print(f"    {label:<35} {count} failure(s)")
        print()

    def save(self) -> None:
        """Persist all task records to task_log.json."""
        with open(self.log_path, "w") as f:
            json.dump(list(self._tasks.values()), f, indent=2, default=str)
        logger.debug(f"Task log saved to {self.log_path}")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _load_existing(self) -> None:
        """Load existing task log if it exists."""
        if self.log_path.exists():
            try:
                with open(self.log_path) as f:
                    tasks = json.load(f)
                self._tasks = {t["task_id"]: t for t in tasks}
                logger.debug(f"Loaded {len(self._tasks)} tasks from {self.log_path}")
            except (json.JSONDecodeError, KeyError):
                logger.warning(f"Could not load {self.log_path}, starting fresh.")
                self._tasks = {}

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _serialise(obj: Any) -> Any:
        """Make an object JSON-safe."""
        if obj is None:
            return None
        if isinstance(obj, (str, int, float, bool)):
            return obj
        if isinstance(obj, dict):
            return {k: PipelineTracker._serialise(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [PipelineTracker._serialise(v) for v in obj]
        # Pydantic models and enums
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        if hasattr(obj, "value"):
            return obj.value
        return str(obj)


# ── Module-level default tracker instance ────────────────────────────────────
# Import this for convenience:  from tracker import tracker
tracker = PipelineTracker()