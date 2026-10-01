"""
eval_report.py
--------------
EVAL-4 + EVAL-5 + EVAL-6: Full Sprint 3 evaluation suite.

Runs:
    1. End-to-end pipeline evaluation — all 25 test cases through the full
       5-stage pipeline (LLM parse + task plan + mock robot execution)
    2. Baseline comparison — same cases through the rule-based keyword parser
    3. Side-by-side report — LLM models vs baseline across all metrics

This is the primary evidence for the final report evaluation section.

Usage:
    # Full evaluation (requires API keys)
    python eval_report.py

    # Baseline only (no API key needed)
    python eval_report.py --baseline-only

    # Specific LLM models
    python eval_report.py --models openai gemini

    # Export to CSV and JSON
    python eval_report.py --export
"""

import sys
import os
import json
import argparse
import time
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from test_cases import TEST_CASES, get_all_categories
from baseline_parser import run_baseline_evaluation
from model_registry import get_available_models, MODEL_DISPLAY_NAMES

SEP  = "═" * 70
SEP2 = "─" * 70


# ── End-to-end pipeline evaluation ────────────────────────────────────────────

def run_pipeline_evaluation(
    models: Optional[list[str]] = None,
    verbose: bool = True,
) -> list[dict]:
    """
    EVAL-4: Run all test cases through the full 5-stage pipeline.
    Uses MockRobot so no PyBullet required.

    Returns results in same format as baseline_parser for direct comparison.
    """
    from task_planner.planner import TaskPlanner
    from execution.mock_robot import MockRobot
    from execution.executor   import Executor

    if models is None:
        models = get_available_models()

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

    all_results = []

    for model in models:
        if verbose:
            print(f"\n  Running pipeline evaluation: {MODEL_DISPLAY_NAMES.get(model, model)}")
            print(f"  {SEP2}")

        try:
            from model_registry import get_chain
            from langchain_core.output_parsers import PydanticOutputParser
            from schema import ParsedInstruction
            from edge_cases import (is_empty_instruction, is_too_vague,
                                    normalise_instruction, validate_parsed_result,
                                    make_vague_result)
            from prompts import build_system_prompt
            from langchain_core.prompts import ChatPromptTemplate

            output_parser = PydanticOutputParser(pydantic_object=ParsedInstruction)
            system_prompt = build_system_prompt(output_parser.get_format_instructions())
            prompt        = ChatPromptTemplate.from_messages([
                ("system", system_prompt),
                ("human",  "Instruction: {instruction}"),
            ])
            llm   = get_chain(model)

        except Exception as e:
            if verbose:
                print(f"  ⚠  Skipping {model}: {e}")
            continue

        for case in TEST_CASES:
            start = time.perf_counter()
            row   = {
                "model":               model,
                "model_display":       MODEL_DISPLAY_NAMES.get(model, model),
                "case_id":             case.id,
                "category":            case.category,
                "instruction":         case.instruction,
                "parse_success":       False,
                "fully_correct":       False,
                "action_correct":      False,
                "object_correct":      False,
                "destination_correct": False,
                "spatial_correct":     False,
                "confidence_correct":  False,
                "pipeline_success":    False,
                "latency_ms":          0.0,
                "error":               None,
                "parsed":              None,
            }

            try:
                # Stage 1: LLM parse
                from langchain_core.exceptions import OutputParserException
                from parser import parse_instruction
                parsed = parse_instruction(case.instruction)

                row["parse_success"]      = True
                row["action_correct"]     = parsed.action.value == case.expected_action
                row["object_correct"]     = (
                    case.expected_object.lower() in parsed.object_target.lower() or
                    parsed.object_target.lower() in case.expected_object.lower()
                )
                row["destination_correct"] = (
                    parsed.destination is None if case.expected_destination is None
                    else parsed.destination is not None and
                         case.expected_destination.lower() in parsed.destination.lower()
                )
                row["spatial_correct"] = (
                    parsed.spatial_relation is None if case.expected_spatial is None
                    else parsed.spatial_relation is not None and
                         case.expected_spatial.lower() in parsed.spatial_relation.lower()
                )
                row["confidence_correct"] = parsed.confidence.value == case.expected_confidence
                row["parsed"]             = parsed.model_dump(mode="json")

                from schema import ConfidenceLevel
                if parsed.confidence == ConfidenceLevel.LOW:
                    row["pipeline_success"] = True  # graceful low-confidence exit
                    row["fully_correct"]    = all([
                        row["action_correct"], row["object_correct"],
                        row["destination_correct"], row["spatial_correct"],
                    ])
                else:
                    # Stage 2: Scene lookup (stub)
                    scene = DEFAULT_SCENE

                    # Stage 3: Task planning
                    planner = TaskPlanner()
                    plan    = planner.generate_plan(parsed, scene)

                    # Stage 4: Execution
                    robot    = MockRobot()
                    robot.load_scene(scene)
                    exec_res = Executor(robot).execute(plan, verbose=False)

                    row["pipeline_success"] = exec_res.success
                    row["fully_correct"]    = exec_res.success and all([
                        row["action_correct"], row["object_correct"],
                        row["destination_correct"], row["spatial_correct"],
                    ])

            except ValueError:
                # Object not found in scene — expected for edge cases
                row["pipeline_success"] = False
                row["fully_correct"]    = (case.category == "edge_case" and
                                           case.expected_confidence == "low")
            except Exception as e:
                row["error"] = str(e)

            row["latency_ms"] = (time.perf_counter() - start) * 1000
            all_results.append(row)

            if verbose:
                s = "✓" if row["fully_correct"] else ("✗" if row["parse_success"] else "!")
                print(f"  [{case.id}] {case.instruction[:48]:<48} {s}  {row['latency_ms']:6.0f}ms")

    return all_results


# ── Metrics from raw results ───────────────────────────────────────────────────

def _pct(correct: int, total: int) -> float:
    return round(100 * correct / total, 1) if total > 0 else 0.0


def compute_simple_metrics(results: list[dict]) -> dict:
    """Compute metrics grouped by model and category."""
    from collections import defaultdict
    import statistics

    by_model: dict[str, list] = defaultdict(list)
    for r in results:
        by_model[r["model"]].append(r)

    output = {}
    for model, rows in by_model.items():
        n        = len(rows)
        latencies = [r["latency_ms"] for r in rows if r["parse_success"]]
        by_cat: dict[str, list] = defaultdict(list)
        for r in rows:
            by_cat[r["category"]].append(r)

        overall = {
            "total":               n,
            "parse_success_rate":  _pct(sum(r["parse_success"]  for r in rows), n),
            "instruction_accuracy":_pct(sum(r["fully_correct"]  for r in rows), n),
            "action_accuracy":     _pct(sum(r["action_correct"] for r in rows), n),
            "object_accuracy":     _pct(sum(r["object_correct"] for r in rows), n),
            "destination_accuracy":_pct(sum(r["destination_correct"] for r in rows), n),
            "spatial_accuracy":    _pct(sum(r["spatial_correct"] for r in rows), n),
            "avg_latency_ms":      round(statistics.mean(latencies), 1) if latencies else 0.0,
            "error_rate":          _pct(sum(not r["parse_success"] for r in rows), n),
        }
        by_category = {
            cat: {
                "instruction_accuracy": _pct(sum(r["fully_correct"] for r in cat_rows),
                                              len(cat_rows)),
                "avg_latency_ms":       round(
                    statistics.mean([r["latency_ms"] for r in cat_rows
                                     if r["parse_success"]]) or 0, 1
                ) if any(r["parse_success"] for r in cat_rows) else 0.0,
                "error_rate":           _pct(sum(not r["parse_success"] for r in cat_rows),
                                              len(cat_rows)),
            }
            for cat, cat_rows in by_cat.items()
        }

        display = rows[0]["model_display"] if rows else model
        output[model] = {"display": display, "overall": overall, "by_category": by_category}

    return output


# ── Report printer ─────────────────────────────────────────────────────────────

def print_evaluation_report(
    llm_results:      list[dict],
    baseline_results: list[dict],
) -> None:
    """Print the full comparative report to stdout."""

    all_results = llm_results + baseline_results
    metrics     = compute_simple_metrics(all_results)
    models      = list(metrics.keys())

    print(f"\n{SEP}")
    print("  SPRINT 3 — FULL EVALUATION REPORT")
    print(f"  Models:  {', '.join(metrics[m]['display'] for m in models)}")
    print(f"  Cases:   {len(TEST_CASES)} test instructions · {len(get_all_categories())} categories")
    print(SEP)

    # ── Overall comparison table ───────────────────────────────────────────────
    col_w    = 22
    label_w  = 26
    displays = {m: metrics[m]["display"][:col_w] for m in models}

    print(f"\n  {'OVERALL COMPARISON':^{label_w + col_w * len(models)}}")
    print(f"  {SEP2}")
    print(f"  {'Metric':<{label_w}}" +
          "".join(f"{displays[m]:>{col_w}}" for m in models))
    print(f"  {SEP2}")

    rows = [
        ("Parse success rate (%)",      "parse_success_rate"),
        ("Instruction accuracy (%)",    "instruction_accuracy"),
        ("Action accuracy (%)",         "action_accuracy"),
        ("Object accuracy (%)",         "object_accuracy"),
        ("Destination accuracy (%)",    "destination_accuracy"),
        ("Spatial accuracy (%)",        "spatial_accuracy"),
        ("Avg latency (ms)",            "avg_latency_ms"),
        ("Error rate (%)",              "error_rate"),
    ]
    for label, key in rows:
        row = f"  {label:<{label_w}}"
        for m in models:
            val = metrics[m]["overall"].get(key, "—")
            row += f"{val:>{col_w}}"
        print(row)

    print(f"  {SEP2}")

    # ── Per-category breakdown ─────────────────────────────────────────────────
    categories = sorted(get_all_categories())
    print(f"\n  ACCURACY BY USE CASE CATEGORY (%)\n  {SEP2}")
    print(f"  {'Category':<16}" +
          "".join(f"{displays[m]:>{col_w}}" for m in models))
    print(f"  {SEP2}")

    for cat in categories:
        row = f"  {cat:<16}"
        for m in models:
            val = metrics[m]["by_category"].get(cat, {}).get("instruction_accuracy", "—")
            row += f"{val:>{col_w}}"
        print(row)
    print(f"  {SEP2}")

    # ── Key findings ───────────────────────────────────────────────────────────
    print(f"\n  KEY FINDINGS\n  {SEP2}")

    # Best model overall
    llm_models  = [m for m in models if m != "baseline"]
    if llm_models:
        best = max(llm_models,
                   key=lambda m: metrics[m]["overall"]["instruction_accuracy"])
        print(f"\n  Best LLM overall:  {metrics[best]['display']}")
        print(f"  Accuracy:          {metrics[best]['overall']['instruction_accuracy']}%")
        print(f"  Avg latency:       {metrics[best]['overall']['avg_latency_ms']}ms")

    # LLM vs baseline
    if "baseline" in metrics and llm_models:
        base_acc = metrics["baseline"]["overall"]["instruction_accuracy"]
        best_acc = metrics[best]["overall"]["instruction_accuracy"]
        gain     = round(best_acc - base_acc, 1)
        print(f"\n  LLM vs Baseline:")
        print(f"  Baseline accuracy: {base_acc}%")
        print(f"  Best LLM accuracy: {best_acc}%")
        print(f"  Improvement:       +{gain}pp over rule-based baseline")

    # Best category per model
    print(f"\n  Best category per LLM model:")
    for m in llm_models:
        cat_metrics = metrics[m]["by_category"]
        if cat_metrics:
            best_cat = max(cat_metrics, key=lambda c: cat_metrics[c]["instruction_accuracy"])
            print(f"  {metrics[m]['display']:<35} best: {best_cat} "
                  f"({cat_metrics[best_cat]['instruction_accuracy']}%)")

    print(f"\n{SEP}\n")


# ── Export ─────────────────────────────────────────────────────────────────────

def export_results(
    llm_results:      list[dict],
    baseline_results: list[dict],
    csv_path:  str = "eval_report.csv",
    json_path: str = "eval_report.json",
) -> None:
    import csv

    all_results = llm_results + baseline_results
    metrics     = compute_simple_metrics(all_results)
    models      = list(metrics.keys())
    categories  = sorted(get_all_categories()) + ["OVERALL"]

    # CSV
    fieldnames = ["model", "category", "instruction_accuracy", "parse_success_rate",
                  "action_accuracy", "object_accuracy", "destination_accuracy",
                  "spatial_accuracy", "avg_latency_ms", "error_rate"]
    rows = []
    for m in models:
        for cat in categories:
            if cat == "OVERALL":
                data = metrics[m]["overall"]
            else:
                data = metrics[m]["by_category"].get(cat, {})
            rows.append({
                "model":    metrics[m]["display"],
                "category": cat,
                **{k: data.get(k, "") for k in fieldnames[2:]},
            })

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV exported → {csv_path}")

    # JSON (raw results)
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"  JSON exported → {json_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sprint 3 Full Evaluation Report")
    ap.add_argument("--models",        nargs="+", choices=["openai", "gemini", "deepseek"])
    ap.add_argument("--baseline-only", action="store_true")
    ap.add_argument("--export",        action="store_true")
    ap.add_argument("--quiet",  "-q",  action="store_true")
    args = ap.parse_args()

    verbose = not args.quiet

    # Always run baseline
    print(f"\n{SEP}\n  Running baseline evaluation...\n{SEP2}")
    baseline = run_baseline_evaluation(verbose=verbose)

    llm_results = []
    if not args.baseline_only:
        models = args.models or get_available_models()
        if models:
            print(f"\n{SEP}\n  Running LLM pipeline evaluation...\n{SEP2}")
            llm_results = run_pipeline_evaluation(models=models, verbose=verbose)
        else:
            print("  No LLM API keys found — running baseline only.")

    print_evaluation_report(llm_results, baseline)

    if args.export:
        export_results(llm_results, baseline)
