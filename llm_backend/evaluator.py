"""
evaluator.py
------------
Runs all configured LLM models against the full test suite and
collects raw results for metric calculation.

Each result captures:
    - model name
    - test case ID and category
    - parsed output (or error)
    - latency in milliseconds
    - whether JSON parsing succeeded
    - field-level correctness scores

Usage:
    from evaluator import run_evaluation
    results = run_evaluation()                    # all models, all cases
    results = run_evaluation(models=["openai"])   # one model
    results = run_evaluation(category="spatial")  # one category
"""

import time
import logging
from typing import Optional

from langchain_core.exceptions import OutputParserException

from .schema import ParsedInstruction
from .test_cases import TEST_CASES, TestCase, get_cases_by_category
from .edge_cases import (
    is_empty_instruction,
    is_too_vague,
    normalise_instruction,
    validate_parsed_result,
    make_vague_result,
)
from .model_registry import get_chain, get_available_models, MODEL_DISPLAY_NAMES

logger = logging.getLogger(__name__)

# ── Result dataclass ───────────────────────────────────────────────────────────
from dataclasses import dataclass, field as dc_field


@dataclass
class EvalResult:
    model:              str
    model_display:      str
    case_id:            str
    category:           str
    instruction:        str

    # Raw output
    parsed:             Optional[ParsedInstruction] = None
    error:              Optional[str] = None

    # Timing
    latency_ms:         float = 0.0

    # JSON success
    parse_success:      bool = False

    # Field-level correctness (True/False/None if not applicable)
    action_correct:     Optional[bool] = None
    object_correct:     Optional[bool] = None
    destination_correct: Optional[bool] = None
    spatial_correct:    Optional[bool] = None
    confidence_correct: Optional[bool] = None

    # Composite
    fully_correct:      bool = False


def _score_result(result: EvalResult, case: TestCase) -> EvalResult:
    """
    Compare parsed output against the test case ground truth.
    Populates all *_correct fields and fully_correct.
    """
    if result.parsed is None:
        return result

    p = result.parsed

    result.action_correct = (p.action.value == case.expected_action)

    # Object: partial match acceptable (e.g. "red block" in "red block")
    result.object_correct = (
        case.expected_object.lower() in p.object_target.lower()
        or p.object_target.lower() in case.expected_object.lower()
    )

    # Destination: None expected → None returned is correct
    if case.expected_destination is None:
        result.destination_correct = (p.destination is None)
    else:
        result.destination_correct = (
            p.destination is not None and
            case.expected_destination.lower() in p.destination.lower()
        )

    # Spatial: None expected → None returned is correct
    if case.expected_spatial is None:
        result.spatial_correct = (p.spatial_relation is None)
    else:
        result.spatial_correct = (
            p.spatial_relation is not None and
            case.expected_spatial.lower() in p.spatial_relation.lower()
        )

    result.confidence_correct = (p.confidence.value == case.expected_confidence)

    result.fully_correct = all([
        result.action_correct,
        result.object_correct,
        result.destination_correct,
        result.spatial_correct,
    ])

    return result


def _run_single(
    chain,
    model: str,
    case: TestCase,
    max_retries: int = 2,
) -> EvalResult:
    """
    Run one test case through one model and return an EvalResult.
    """
    result = EvalResult(
        model=model,
        model_display=MODEL_DISPLAY_NAMES.get(model, model),
        case_id=case.id,
        category=case.category,
        instruction=case.instruction,
    )

    # Pre-processing
    if is_empty_instruction(case.instruction):
        result.error = "Empty instruction"
        result.parse_success = False
        return result

    instruction = normalise_instruction(case.instruction)

    if is_too_vague(instruction):
        start = time.perf_counter()
        parsed = make_vague_result(instruction)
        result.latency_ms = (time.perf_counter() - start) * 1000
        result.parsed = parsed
        result.parse_success = True
        return _score_result(result, case)

    # LLM call with retries
    last_error = None
    start = time.perf_counter()

    for attempt in range(1, max_retries + 1):
        try:
            parsed = chain.invoke({"instruction": instruction})
            result.latency_ms = (time.perf_counter() - start) * 1000
            result.parsed = validate_parsed_result(parsed)
            result.parse_success = True
            return _score_result(result, case)

        except OutputParserException as e:
            last_error = str(e)
            logger.warning(f"[{model}][{case.id}] Attempt {attempt} OutputParserException")

        except Exception as e:
            last_error = str(e)
            logger.warning(f"[{model}][{case.id}] Attempt {attempt} {type(e).__name__}: {e}")

    result.latency_ms = (time.perf_counter() - start) * 1000
    result.error = last_error
    result.parse_success = False
    return result


def run_evaluation(
    models: Optional[list[str]] = None,
    category: Optional[str] = None,
    max_retries: int = 2,
    verbose: bool = True,
) -> list[EvalResult]:
    """
    Run the full evaluation suite.

    Args:
        models:      List of model names to test. Defaults to all available.
        category:    If set, only run test cases from this category.
        max_retries: Retries per case on JSON parse failure.
        verbose:     Print progress to stdout.

    Returns:
        List of EvalResult objects, one per (model, test_case) combination.
    """
    if models is None:
        models = get_available_models()

    if not models:
        raise RuntimeError(
            "No models available. Check that at least one API key is set in .env."
        )

    cases = get_cases_by_category(category) if category else TEST_CASES

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Evaluation: {len(models)} model(s) × {len(cases)} test cases")
        print(f"  Models: {', '.join(models)}")
        if category:
            print(f"  Category filter: {category}")
        print(f"{'='*60}\n")

    all_results: list[EvalResult] = []

    for model in models:
        if verbose:
            print(f"Running model: {MODEL_DISPLAY_NAMES.get(model, model)}")
            print("-" * 40)

        try:
            chain = get_chain(model)
        except (EnvironmentError, ImportError) as e:
            logger.error(f"Cannot load model '{model}': {e}")
            if verbose:
                print(f"  ⚠ Skipping {model}: {e}")
            continue

        for case in cases:
            if verbose:
                print(f"  [{case.id}] {case.instruction[:55]:<55}", end=" ", flush=True)

            result = _run_single(chain, model, case, max_retries)
            all_results.append(result)

            if verbose:
                status = "✓" if result.fully_correct else ("✗" if result.parse_success else "!")
                latency = f"{result.latency_ms:6.0f}ms"
                print(f"{status}  {latency}")

        if verbose:
            print()

    return all_results