"""
baseline_parser.py
------------------
EVAL-5: Rule-based baseline parser — no LLM, no API calls.

Uses keyword matching to extract structured output from natural language
instructions. Provides a baseline comparison point for the LLM-based pipeline.

Research question this answers:
    Does using an LLM provide meaningful benefit over a simpler keyword-matching
    approach for industrial task planning instructions?

Expected findings:
    - Baseline performs well on simple instructions
    - Baseline fails on spatial relations (no positional reasoning)
    - Baseline fails on synonyms not in its keyword list
    - Baseline fails on ambiguous instructions (no confidence calibration)
    - LLMs outperform on all non-trivial categories

Usage:
    from baseline_parser import BaselineParser
    parser = BaselineParser()
    result = parser.parse("pick up the red block")
    print(result)

    # Run full comparison
    from baseline_parser import run_baseline_evaluation
    results = run_baseline_evaluation()
"""

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# ── Keyword maps ───────────────────────────────────────────────────────────────

ACTION_KEYWORDS: dict[str, list[str]] = {
    "pick":   ["pick", "grab", "take", "get", "lift", "collect", "fetch"],
    "place":  ["place", "put", "drop", "set", "deposit", "release"],
    "move":   ["move", "transfer", "shift", "bring", "push", "carry"],
    "locate": ["locate", "find", "search", "where", "look", "identify"],
}

COLOUR_KEYWORDS  = ["red", "blue", "green", "yellow", "orange", "purple", "white", "black"]
OBJECT_KEYWORDS  = ["block", "cube", "box", "component", "part", "item", "piece", "object"]
LOCATION_KEYWORDS = {
    "left tray":    ["left tray", "left bin", "left container"],
    "right tray":   ["right tray", "right bin", "right container"],
    "workstation":  ["workstation", "work station", "station", "bench"],
    "tray":         ["tray", "bin", "container", "basket"],
}

SPATIAL_KEYWORDS: dict[str, list[str]] = {
    "left of":    ["left of", "to the left", "left side of"],
    "right of":   ["right of", "to the right", "right side of"],
    "near":       ["near", "close to", "next to", "beside", "adjacent"],
    "on top of":  ["on top of", "on top", "above", "over"],
    "in":         ["in", "inside", "into", "within"],
}


# ── Result model ───────────────────────────────────────────────────────────────

@dataclass
class BaselineResult:
    action:           Optional[str] = None
    object_target:    Optional[str] = None
    destination:      Optional[str] = None
    spatial_relation: Optional[str] = None
    confidence:       str           = "high"
    raw_instruction:  str           = ""
    parse_success:    bool          = False
    latency_ms:       float         = 0.0
    notes:            Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action":           self.action,
            "object_target":    self.object_target,
            "destination":      self.destination,
            "spatial_relation": self.spatial_relation,
            "confidence":       self.confidence,
            "raw_instruction":  self.raw_instruction,
            "parse_success":    self.parse_success,
            "latency_ms":       self.latency_ms,
            "notes":            self.notes,
        }


# ── Baseline parser ────────────────────────────────────────────────────────────

class BaselineParser:
    """
    Rule-based keyword parser — no LLM, no external API.

    Parsing strategy:
    1. Normalise text (lowercase, strip punctuation)
    2. Match action keywords → extract action
    3. Match colour + object keywords → extract object_target
    4. Match location keywords → extract destination
    5. Match spatial keywords → extract spatial_relation
    6. Assign confidence based on how many fields were found
    """

    def parse(self, instruction: str) -> BaselineResult:
        """
        Parse a natural language instruction using keyword matching.

        Args:
            instruction: Raw instruction string

        Returns:
            BaselineResult with extracted fields
        """
        start = time.perf_counter()

        if not instruction or not instruction.strip():
            return BaselineResult(
                raw_instruction=instruction or "",
                parse_success=False,
                confidence="low",
                notes="Empty instruction",
                latency_ms=0.0,
            )

        text   = instruction.lower().strip()
        text   = re.sub(r"[^\w\s]", " ", text)
        text   = re.sub(r"\s+", " ", text)

        action           = self._extract_action(text)
        object_target    = self._extract_object(text)
        destination      = self._extract_destination(text)
        spatial_relation = self._extract_spatial(text)
        confidence       = self._assign_confidence(action, object_target)

        latency = (time.perf_counter() - start) * 1000

        return BaselineResult(
            action=action,
            object_target=object_target,
            destination=destination,
            spatial_relation=spatial_relation,
            confidence=confidence,
            raw_instruction=instruction,
            parse_success=(action is not None and object_target is not None),
            latency_ms=latency,
            notes=self._build_notes(action, object_target, destination),
        )

    # ── Extraction helpers ─────────────────────────────────────────────────────

    def _extract_action(self, text: str) -> Optional[str]:
        for action, keywords in ACTION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return action
        return None

    def _extract_object(self, text: str) -> Optional[str]:
        found_colour = None
        found_object = None

        for colour in COLOUR_KEYWORDS:
            if colour in text:
                found_colour = colour
                break

        for obj in OBJECT_KEYWORDS:
            if obj in text:
                found_object = obj
                break

        if found_colour and found_object:
            return f"{found_colour} {found_object}"
        elif found_colour:
            return f"{found_colour} block"
        elif found_object:
            return found_object
        return None

    def _extract_destination(self, text: str) -> Optional[str]:
        # Use original instruction text (not lowered/stripped) for multi-word matching
        for label, keywords in LOCATION_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return label
        return None

    def _extract_spatial(self, text: str) -> Optional[str]:
        for relation, keywords in SPATIAL_KEYWORDS.items():
            for kw in keywords:
                if kw in text:
                    return relation
        return None

    def _assign_confidence(
        self,
        action: Optional[str],
        object_target: Optional[str],
    ) -> str:
        if action and object_target:
            return "high"
        elif action or object_target:
            return "medium"
        return "low"

    def _build_notes(
        self,
        action: Optional[str],
        object_target: Optional[str],
        destination: Optional[str],
    ) -> Optional[str]:
        issues = []
        if action is None:
            issues.append("No action keyword matched")
        if object_target is None:
            issues.append("No object/colour keyword matched")
        if issues:
            return "; ".join(issues)
        return None


# ── Baseline evaluation runner ─────────────────────────────────────────────────

def run_baseline_evaluation(verbose: bool = True) -> list[dict]:
    """
    Run the baseline parser against all 25 test cases.
    Returns results in the same format as evaluator.py EvalResult
    so they can be compared directly in comparison_report.py.

    Args:
        verbose: Print progress per case

    Returns:
        List of result dicts compatible with metrics.py
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from test_cases import TEST_CASES

    parser  = BaselineParser()
    results = []

    if verbose:
        print(f"\n{'='*55}")
        print(f"  Baseline Evaluation — Rule-Based Parser")
        print(f"  {len(TEST_CASES)} test cases")
        print(f"{'='*55}\n")

    for case in TEST_CASES:
        result = parser.parse(case.instruction)

        # Score against ground truth
        action_correct = (result.action == case.expected_action) if result.action else False
        object_correct = (
            case.expected_object.lower() in (result.object_target or "").lower()
            or (result.object_target or "").lower() in case.expected_object.lower()
        ) if result.object_target else False
        dest_correct = (
            result.destination is None
            if case.expected_destination is None
            else (
                result.destination is not None and
                case.expected_destination.lower() in result.destination.lower()
            )
        )
        spatial_correct = (
            result.spatial_relation is None
            if case.expected_spatial is None
            else (
                result.spatial_relation is not None and
                case.expected_spatial.lower() in result.spatial_relation.lower()
            )
        )
        fully_correct = all([action_correct, object_correct, dest_correct, spatial_correct])

        row = {
            "model":               "baseline",
            "model_display":       "Rule-Based (No LLM)",
            "case_id":             case.id,
            "category":            case.category,
            "instruction":         case.instruction,
            "parse_success":       result.parse_success,
            "fully_correct":       fully_correct,
            "action_correct":      action_correct,
            "object_correct":      object_correct,
            "destination_correct": dest_correct,
            "spatial_correct":     spatial_correct,
            "confidence_correct":  result.confidence == case.expected_confidence,
            "latency_ms":          result.latency_ms,
            "error":               None if result.parse_success else result.notes,
            "parsed":              result.to_dict(),
        }
        results.append(row)

        if verbose:
            status = "✓" if fully_correct else ("✗" if result.parse_success else "!")
            print(f"  [{case.id}] {case.instruction[:50]:<50} {status}  {result.latency_ms:.2f}ms")

    if verbose:
        total     = len(results)
        correct   = sum(r["fully_correct"] for r in results)
        parse_ok  = sum(r["parse_success"] for r in results)
        avg_lat   = sum(r["latency_ms"] for r in results) / total
        print(f"\n  Summary:")
        print(f"  Parse success:        {parse_ok}/{total} ({100*parse_ok/total:.1f}%)")
        print(f"  Instruction accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
        print(f"  Avg latency:          {avg_lat:.3f}ms  (no API — local only)\n")

    return results
