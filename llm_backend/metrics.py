"""
metrics.py
----------
Calculates evaluation metrics from raw EvalResult objects.

Metrics computed per model:
    - parse_success_rate     % of instructions that returned valid JSON
    - instruction_accuracy   % of fully correct results (action+object+dest+spatial)
    - action_accuracy        % correct action extracted
    - object_accuracy        % correct object extracted
    - destination_accuracy   % correct destination extracted
    - spatial_accuracy       % correct spatial relation extracted
    - confidence_calibration % where confidence level matched expected
    - avg_latency_ms         mean response time in milliseconds
    - p95_latency_ms         95th percentile response time
    - error_rate             % of calls that failed entirely

Metrics also broken down by use case category.

Usage:
    from evaluator import run_evaluation
    from metrics import compute_metrics, print_metrics_table

    results = run_evaluation()
    metrics = compute_metrics(results)
    print_metrics_table(metrics)
"""

import statistics
from collections import defaultdict
from typing import Any

from .evaluator import EvalResult


# ── Metric computation ─────────────────────────────────────────────────────────

def _safe_pct(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 1) if denominator > 0 else 0.0


def _compute_for_results(results: list[EvalResult]) -> dict[str, Any]:
    """Compute all metrics for a flat list of EvalResult objects."""
    if not results:
        return {}

    n = len(results)
    latencies = [r.latency_ms for r in results if r.parse_success]

    return {
        "total_cases":            n,
        "parse_success_rate":     _safe_pct(sum(r.parse_success for r in results), n),
        "instruction_accuracy":   _safe_pct(sum(r.fully_correct for r in results), n),
        "action_accuracy":        _safe_pct(
            sum(r.action_correct for r in results if r.action_correct is not None), n
        ),
        "object_accuracy":        _safe_pct(
            sum(r.object_correct for r in results if r.object_correct is not None), n
        ),
        "destination_accuracy":   _safe_pct(
            sum(r.destination_correct for r in results if r.destination_correct is not None), n
        ),
        "spatial_accuracy":       _safe_pct(
            sum(r.spatial_correct for r in results if r.spatial_correct is not None), n
        ),
        "confidence_calibration": _safe_pct(
            sum(r.confidence_correct for r in results if r.confidence_correct is not None), n
        ),
        "avg_latency_ms":         round(statistics.mean(latencies), 1) if latencies else 0.0,
        "p95_latency_ms":         round(
            sorted(latencies)[int(0.95 * len(latencies)) - 1], 1
        ) if len(latencies) >= 2 else (latencies[0] if latencies else 0.0),
        "error_rate":             _safe_pct(sum(not r.parse_success for r in results), n),
    }


def compute_metrics(results: list[EvalResult]) -> dict[str, Any]:
    """
    Compute full metrics summary from evaluation results.

    Returns a dict with structure:
    {
        "by_model": {
            "openai": { overall: {...}, by_category: { "simple": {...}, ... } },
            ...
        },
        "models":   ["openai", "gemini", "deepseek"]
    }
    """
    # Group by model
    by_model: dict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        by_model[r.model].append(r)

    output = {"by_model": {}, "models": sorted(by_model.keys())}

    for model, model_results in by_model.items():
        # Group by category
        by_category: dict[str, list[EvalResult]] = defaultdict(list)
        for r in model_results:
            by_category[r.category].append(r)

        output["by_model"][model] = {
            "display_name": model_results[0].model_display if model_results else model,
            "overall":      _compute_for_results(model_results),
            "by_category":  {
                cat: _compute_for_results(cat_results)
                for cat, cat_results in by_category.items()
            },
        }

    return output


# ── Pretty printing ────────────────────────────────────────────────────────────

def print_metrics_table(metrics: dict[str, Any]) -> None:
    """Print a formatted comparison table to stdout."""
    models = metrics["models"]
    if not models:
        print("No results to display.")
        return

    display = {m: metrics["by_model"][m]["display_name"] for m in models}
    col_w = max(len(d) for d in display.values()) + 2

    metric_rows = [
        ("Parse success rate (%)",     "parse_success_rate"),
        ("Instruction accuracy (%)",   "instruction_accuracy"),
        ("Action accuracy (%)",        "action_accuracy"),
        ("Object accuracy (%)",        "object_accuracy"),
        ("Destination accuracy (%)",   "destination_accuracy"),
        ("Spatial accuracy (%)",       "spatial_accuracy"),
        ("Confidence calibration (%)", "confidence_calibration"),
        ("Avg latency (ms)",           "avg_latency_ms"),
        ("P95 latency (ms)",           "p95_latency_ms"),
        ("Error rate (%)",             "error_rate"),
    ]

    label_w = max(len(label) for label, _ in metric_rows) + 2

    # Header
    sep = "─" * (label_w + col_w * len(models) + len(models))
    print(f"\n{'OVERALL METRICS COMPARISON':^{label_w + col_w * len(models)}}")
    print(sep)
    header = f"{'Metric':<{label_w}}" + "".join(f"{display[m]:>{col_w}}" for m in models)
    print(header)
    print(sep)

    for label, key in metric_rows:
        row = f"{label:<{label_w}}"
        for m in models:
            val = metrics["by_model"][m]["overall"].get(key, "—")
            row += f"{val:>{col_w}}"
        print(row)

    print(sep)

    # Per-category breakdown
    all_categories = sorted(set(
        cat
        for m in models
        for cat in metrics["by_model"][m]["by_category"]
    ))

    for cat in all_categories:
        print(f"\n  Category: {cat.upper()}")
        cat_sep = "─" * (label_w + col_w * len(models) + len(models))
        print(f"  {cat_sep}")
        for label, key in [
            ("Instruction accuracy (%)", "instruction_accuracy"),
            ("Avg latency (ms)",         "avg_latency_ms"),
            ("Error rate (%)",           "error_rate"),
        ]:
            row = f"  {label:<{label_w - 2}}"
            for m in models:
                cat_data = metrics["by_model"][m]["by_category"].get(cat, {})
                val = cat_data.get(key, "—")
                row += f"{val:>{col_w}}"
            print(row)

    print()


def export_metrics_csv(metrics: dict[str, Any], path: str = "evaluation_metrics.csv") -> None:
    """
    Export the full metrics breakdown to a CSV file for reports and charts.
    """
    import csv

    models = metrics["models"]
    all_categories = sorted(set(
        cat
        for m in models
        for cat in metrics["by_model"][m]["by_category"]
    ))

    metric_keys = [
        "parse_success_rate", "instruction_accuracy", "action_accuracy",
        "object_accuracy", "destination_accuracy", "spatial_accuracy",
        "confidence_calibration", "avg_latency_ms", "p95_latency_ms", "error_rate",
    ]

    rows = []

    # Overall rows
    for m in models:
        row = {
            "model": metrics["by_model"][m]["display_name"],
            "category": "OVERALL",
        }
        for key in metric_keys:
            row[key] = metrics["by_model"][m]["overall"].get(key, "")
        rows.append(row)

    # Per-category rows
    for cat in all_categories:
        for m in models:
            cat_data = metrics["by_model"][m]["by_category"].get(cat, {})
            row = {
                "model": metrics["by_model"][m]["display_name"],
                "category": cat,
            }
            for key in metric_keys:
                row[key] = cat_data.get(key, "")
            rows.append(row)

    fieldnames = ["model", "category"] + metric_keys
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Metrics exported to {path}")