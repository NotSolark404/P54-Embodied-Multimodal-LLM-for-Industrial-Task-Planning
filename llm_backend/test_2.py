"""
test_llm_module.py
------------------
Unit tests for the LLM instruction parser module.
Tests are split into:
  - Unit tests (no API calls) — test schema, edge cases, pre/post processing
  - Integration tests         — test actual LLM calls (requires API key + credits)

Run all unit tests (fast, no API):
    pytest test_2 -v -m "not integration"

Run everything including LLM calls:
    pytest test_llm_module.py -v
"""

import pytest
from unittest.mock import patch, MagicMock

from schema import ParsedInstruction, ActionType, ConfidenceLevel
from edge_cases import (
    is_empty_instruction,
    is_too_vague,
    normalise_instruction,
    validate_parsed_result,
    make_vague_result,
)


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEMA TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchema:

    def test_valid_full_instruction(self):
        """Schema accepts a fully populated valid instruction."""
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="red block",
            destination="left tray",
            spatial_relation="in",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the red block and place it in the left tray",
            notes=None
        )
        assert result.action == ActionType.PICK
        assert result.object_target == "red block"
        assert result.destination == "left tray"
        assert result.confidence == ConfidenceLevel.HIGH

    def test_valid_minimal_instruction(self):
        """Schema accepts instruction with only required fields."""
        result = ParsedInstruction(
            action=ActionType.LOCATE,
            object_target="yellow block",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="find the yellow block",
        )
        assert result.destination is None
        assert result.spatial_relation is None
        assert result.notes is None

    def test_action_types_are_valid(self):
        """All four action types are accepted."""
        for action in [ActionType.PICK, ActionType.PLACE, ActionType.MOVE, ActionType.LOCATE]:
            result = ParsedInstruction(
                action=action,
                object_target="red block",
                confidence=ConfidenceLevel.HIGH,
                raw_instruction="test",
            )
            assert result.action == action

    def test_confidence_levels_are_valid(self):
        """All three confidence levels are accepted."""
        for level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW]:
            result = ParsedInstruction(
                action=ActionType.PICK,
                object_target="red block",
                confidence=level,
                raw_instruction="test",
            )
            assert result.confidence == level

    def test_invalid_action_raises(self):
        """Schema rejects actions not in the allowed enum."""
        with pytest.raises(Exception):
            ParsedInstruction(
                action="throw",  # not a valid ActionType
                object_target="red block",
                confidence=ConfidenceLevel.HIGH,
                raw_instruction="test",
            )

    def test_model_dump_returns_dict(self):
        """model_dump() returns a plain dict for downstream use."""
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="red block",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick the red block",
        )
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["action"] == "pick"
        assert dumped["object_target"] == "red block"


# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASE UNIT TESTS (no API calls)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    # ── is_empty_instruction ──────────────────────────────────────────────────

    def test_empty_string_is_empty(self):
        assert is_empty_instruction("") is True

    def test_whitespace_only_is_empty(self):
        assert is_empty_instruction("   ") is True

    def test_none_is_empty(self):
        assert is_empty_instruction(None) is True

    def test_valid_instruction_not_empty(self):
        assert is_empty_instruction("pick up the red block") is False

    # ── is_too_vague ─────────────────────────────────────────────────────────

    def test_vague_instruction_detected(self):
        assert is_too_vague("do something with that") is True

    def test_clear_instruction_not_vague(self):
        assert is_too_vague("pick up the red block") is False

    def test_colour_mention_not_vague(self):
        assert is_too_vague("grab the blue one") is False

    def test_action_mention_not_vague(self):
        assert is_too_vague("locate it") is False

    # ── normalise_instruction ─────────────────────────────────────────────────

    def test_strips_whitespace(self):
        assert normalise_instruction("  pick the block  ") == "pick the block"

    def test_collapses_double_spaces(self):
        assert normalise_instruction("pick  up   the   block") == "pick up the block"

    def test_preserves_content(self):
        result = normalise_instruction("pick up the red block")
        assert "red block" in result

    # ── make_vague_result ─────────────────────────────────────────────────────

    def test_vague_result_has_low_confidence(self):
        result = make_vague_result("do something")
        assert result.confidence == ConfidenceLevel.LOW

    def test_vague_result_preserves_instruction(self):
        result = make_vague_result("do something weird")
        assert result.raw_instruction == "do something weird"

    def test_vague_result_has_notes(self):
        result = make_vague_result("hmm")
        assert result.notes is not None
        assert len(result.notes) > 0

    def test_vague_result_object_is_unknown(self):
        result = make_vague_result("do something")
        assert result.object_target == "unknown"

    # ── validate_parsed_result ────────────────────────────────────────────────

    def test_unknown_object_downgrades_confidence(self):
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="unknown",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the thing",
        )
        validated = validate_parsed_result(result)
        assert validated.confidence == ConfidenceLevel.LOW

    def test_known_object_keeps_confidence(self):
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="red block",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the red block",
        )
        validated = validate_parsed_result(result)
        assert validated.confidence == ConfidenceLevel.HIGH

    def test_unknown_destination_adds_notes(self):
        result = ParsedInstruction(
            action=ActionType.PLACE,
            object_target="red block",
            destination="unknown",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="place the red block somewhere",
        )
        validated = validate_parsed_result(result)
        assert validated.notes is not None


# ═══════════════════════════════════════════════════════════════════════════════
# PARSER INTEGRATION TESTS (requires API key + credits)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.integration
class TestParserIntegration:
    """
    These tests make real API calls.
    Run with: pytest test_llm_module.py -v -m integration
    Requires OPENAI_API_KEY in .env and available credits.
    """

    @pytest.fixture(autouse=True)
    def import_parser(self):
        from parser import parse_instruction
        self.parse = parse_instruction

    def test_simple_pick_instruction(self):
        result = self.parse("pick up the red block")
        assert result.action == ActionType.PICK
        assert "red" in result.object_target.lower()
        assert result.confidence == ConfidenceLevel.HIGH

    def test_place_with_destination(self):
        result = self.parse("place the blue cube in the left tray")
        assert result.action == ActionType.PLACE
        assert "blue" in result.object_target.lower()
        assert result.destination is not None
        assert "left" in result.destination.lower()

    def test_move_with_spatial_relation(self):
        result = self.parse("move the green block to the right of the workstation")
        assert result.action == ActionType.MOVE
        assert "green" in result.object_target.lower()
        assert result.spatial_relation is not None

    def test_locate_instruction(self):
        result = self.parse("where is the yellow block")
        assert result.action == ActionType.LOCATE
        assert "yellow" in result.object_target.lower()

    def test_synonym_mapped_correctly(self):
        result = self.parse("grab the red block")
        assert result.action == ActionType.PICK

    def test_ambiguous_instruction_low_confidence(self):
        result = self.parse("put that thing over there")
        assert result.confidence == ConfidenceLevel.LOW

    def test_empty_instruction_raises(self):
        with pytest.raises(ValueError):
            self.parse("")

    def test_whitespace_instruction_raises(self):
        with pytest.raises(ValueError):
            self.parse("   ")

    def test_result_preserves_raw_instruction(self):
        instruction = "pick up the red block"
        result = self.parse(instruction)
        assert result.raw_instruction == instruction

    def test_result_is_parsedinstruction(self):
        result = self.parse("pick up the red block")
        assert isinstance(result, ParsedInstruction)

    def test_model_dump_has_all_fields(self):
        result = self.parse("pick up the red block")
        dumped = result.model_dump()
        expected_keys = {
            "action", "object_target", "destination",
            "spatial_relation", "confidence", "raw_instruction", "notes"
        }
        assert expected_keys == set(dumped.keys())