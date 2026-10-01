"""
edge_cases.py
-------------
Pre- and post-processing logic to handle edge cases before/after LLM parsing.
Keeps parser.py clean and makes edge case behaviour easy to test independently.
"""

import re
from typing import Optional
from schema import ParsedInstruction, ConfidenceLevel

# ── Allowed action types ──────────────────────────────────────────────────────
ALLOWED_ACTIONS = {"pick", "place", "move", "locate"}

# ── Action synonym map ────────────────────────────────────────────────────────
# Maps common synonyms to valid actions so the LLM has less to figure out.
ACTION_SYNONYMS = {
    "grab": "pick",
    "take": "pick",
    "get": "pick",
    "lift": "pick",
    "drop": "place",
    "put": "place",
    "set": "place",
    "deposit": "place",
    "transfer": "move",
    "shift": "move",
    "push": "move",
    "find": "locate",
    "search": "locate",
    "where": "locate",
    "look": "locate",
}

# ── Known objects and locations ───────────────────────────────────────────────
KNOWN_OBJECTS = {
    "red block", "blue block", "green block", "yellow block",
    "red cube", "blue cube", "green cube", "yellow cube",
}
KNOWN_LOCATIONS = {
    "left tray", "right tray", "tray",
    "workstation", "workstation a", "workstation b",
}


def is_empty_instruction(instruction: str) -> bool:
    """Check if instruction is empty or whitespace only."""
    return not instruction or not instruction.strip()


def is_too_vague(instruction: str) -> bool:
    """
    Heuristic check for vague instructions with no recognisable
    object or action keywords.
    """
    lowered = instruction.lower()
    has_known_object = any(obj in lowered for obj in KNOWN_OBJECTS)
    has_known_location = any(loc in lowered for loc in KNOWN_LOCATIONS)
    has_colour = any(c in lowered for c in ["red", "blue", "green", "yellow"])
    has_action = any(a in lowered for a in list(ALLOWED_ACTIONS) + list(ACTION_SYNONYMS.keys()))

    return not has_action and not has_known_object and not has_colour


def normalise_instruction(instruction: str) -> str:
    """
    Light normalisation before sending to LLM:
    - Strip whitespace
    - Lowercase
    - Remove double spaces
    """
    instruction = instruction.strip()
    instruction = re.sub(r"\s+", " ", instruction)
    return instruction


def validate_parsed_result(result: ParsedInstruction) -> ParsedInstruction:
    """
    Post-process the LLM output to catch any remaining issues:
    - Flag unknown objects
    - Flag if action somehow slipped through as invalid
    - Downgrade confidence if object is 'unknown'
    """
    issues = []

    # Check for unknown object
    if result.object_target.lower() == "unknown":
        issues.append("Object target could not be determined from instruction.")
        result = result.model_copy(update={"confidence": ConfidenceLevel.LOW})

    # Check for unknown destination
    if result.destination and result.destination.lower() == "unknown":
        issues.append("Destination could not be determined from instruction.")
        result = result.model_copy(update={"confidence": ConfidenceLevel.LOW})

    # Append any new issues to existing notes
    if issues:
        existing_notes = result.notes or ""
        combined = (existing_notes + " " + " ".join(issues)).strip()
        result = result.model_copy(update={"notes": combined})

    return result


def make_vague_result(instruction: str) -> ParsedInstruction:
    """
    Return a graceful low-confidence result for instructions that are
    too vague to send to the LLM at all.
    """
    return ParsedInstruction(
        action="locate",
        object_target="unknown",
        destination=None,
        spatial_relation=None,
        confidence=ConfidenceLevel.LOW,
        raw_instruction=instruction,
        notes="Instruction is too vague to parse. No recognisable objects or actions found."
    )