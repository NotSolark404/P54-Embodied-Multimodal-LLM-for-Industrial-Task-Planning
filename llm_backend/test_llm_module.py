"""
test_llm_module.py
------------------
Unit and integration tests for the LLM instruction parser module.

Tests are split into:
  - Unit tests (no API calls) -- schema, edge cases, pre/post processing
  - Integration tests          -- real LLM calls (requires API key + credits)

Run unit tests only (fast, no API):
    pytest test_llm_module.py -v -m "not integration"

Run integration tests against OpenAI:
    LLM_BACKEND=openai pytest test_llm_module.py -v -m integration

Run integration tests against Gemini:
    LLM_BACKEND=gemini pytest test_llm_module.py -v -m integration
"""

import pytest
from unittest.mock import patch, MagicMock

from .schema import ParsedInstruction, ActionType, ConfidenceLevel
from .edge_cases import (
    is_empty_instruction,
    is_too_vague,
    normalise_instruction,
    validate_parsed_result,
    make_vague_result,
)


# ===============================================================================
# SCHEMA TESTS
# ===============================================================================

class TestSchema:

    def test_valid_full_instruction(self):
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
        for action in [ActionType.PICK, ActionType.PLACE, ActionType.MOVE, ActionType.LOCATE]:
            result = ParsedInstruction(
                action=action,
                object_target="red block",
                confidence=ConfidenceLevel.HIGH,
                raw_instruction="test",
            )
            assert result.action == action

    def test_confidence_levels_are_valid(self):
        for level in [ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW]:
            result = ParsedInstruction(
                action=ActionType.PICK,
                object_target="red block",
                confidence=level,
                raw_instruction="test",
            )
            assert result.confidence == level

    def test_invalid_action_raises(self):
        with pytest.raises(Exception):
            ParsedInstruction(
                action="throw",
                object_target="red block",
                confidence=ConfidenceLevel.HIGH,
                raw_instruction="test",
            )

    def test_model_dump_returns_dict(self):
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


# ===============================================================================
# EDGE CASE UNIT TESTS (no API calls)
# ===============================================================================

class TestEdgeCases:

    def test_empty_string_is_empty(self):
        assert is_empty_instruction("") is True

    def test_whitespace_only_is_empty(self):
        assert is_empty_instruction("   ") is True

    def test_none_is_empty(self):
        assert is_empty_instruction(None) is True

    def test_valid_instruction_not_empty(self):
        assert is_empty_instruction("pick up the red block") is False

    def test_vague_instruction_detected(self):
        assert is_too_vague("do something with that") is True

    def test_clear_instruction_not_vague(self):
        assert is_too_vague("pick up the red block") is False

    def test_colour_mention_not_vague(self):
        assert is_too_vague("grab the blue one") is False

    def test_action_mention_not_vague(self):
        assert is_too_vague("locate it") is False

    def test_strips_whitespace(self):
        assert normalise_instruction("  pick the block  ") == "pick the block"

    def test_collapses_double_spaces(self):
        assert normalise_instruction("pick  up   the   block") == "pick up the block"

    def test_preserves_content(self):
        assert "red block" in normalise_instruction("pick up the red block")

    def test_vague_result_has_low_confidence(self):
        assert make_vague_result("do something").confidence == ConfidenceLevel.LOW

    def test_vague_result_preserves_instruction(self):
        assert make_vague_result("do something weird").raw_instruction == "do something weird"

    def test_vague_result_has_notes(self):
        result = make_vague_result("hmm")
        assert result.notes and len(result.notes) > 0

    def test_vague_result_object_is_unknown(self):
        assert make_vague_result("do something").object_target == "unknown"

    def test_unknown_object_downgrades_confidence(self):
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="unknown",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the thing",
        )
        assert validate_parsed_result(result).confidence == ConfidenceLevel.LOW

    def test_known_object_keeps_confidence(self):
        result = ParsedInstruction(
            action=ActionType.PICK,
            object_target="red block",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="pick up the red block",
        )
        assert validate_parsed_result(result).confidence == ConfidenceLevel.HIGH

    def test_unknown_destination_adds_notes(self):
        result = ParsedInstruction(
            action=ActionType.PLACE,
            object_target="red block",
            destination="unknown",
            confidence=ConfidenceLevel.HIGH,
            raw_instruction="place the red block somewhere",
        )
        assert validate_parsed_result(result).notes is not None


# ===============================================================================
# BACKEND UNIT TESTS (no API calls)
# ===============================================================================

class TestBackendFactory:

    def test_invalid_backend_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "llamacpp")
        from .backends import get_llm
        with pytest.raises(ValueError, match="Unsupported LLM_BACKEND"):
            get_llm()

    def test_missing_openai_key_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "openai")
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from .backends.openai_backend import build_llm
        with pytest.raises(EnvironmentError):
            build_llm()

    def test_missing_gemini_key_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "gemini")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        from .backends.gemini_backend import build_llm
        with pytest.raises(EnvironmentError):
            build_llm()

    def test_missing_deepseek_key_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "deepseek")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from .backends.deepseek_backend import build_llm
        with pytest.raises(EnvironmentError):
            build_llm()


# ===============================================================================
# PARSER INTEGRATION TESTS  (requires API key + credits)
# Select backend via: LLM_BACKEND=openai|gemini pytest ... -m integration
# ===============================================================================

@pytest.mark.integration
class TestParserIntegration:

    @pytest.fixture(autouse=True)
    def import_parser(self):
        from .custom_LLM_parser import parse_instruction
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
        assert result.spatial_relation is not None

    def test_locate_instruction(self):
        result = self.parse("where is the yellow block")
        assert result.action == ActionType.LOCATE
        assert "yellow" in result.object_target.lower()

    def test_synonym_mapped_correctly(self):
        result = self.parse("grab the red block")
        assert result.action == ActionType.PICK

    def test_vague_short_circuits_without_api_call(self):
        # "do something with that" hits is_too_vague -- no API call made
        result = self.parse("do something with that")
        assert result.confidence == ConfidenceLevel.LOW
        assert result.object_target == "unknown"

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
        assert isinstance(self.parse("pick up the red block"), ParsedInstruction)

    def test_model_dump_has_all_fields(self):
        dumped = self.parse("pick up the red block").model_dump()
        assert {
            "action", "object_target", "destination",
            "spatial_relation", "confidence", "raw_instruction", "notes"
        } == set(dumped.keys())