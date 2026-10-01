# """
# llm_module
# ----------
# Natural language instruction parser for the Multimodal LLM Industrial Task Planning project.
# COS40005 Capstone — Swinburne University / ARENA2036

# Public interface:
#     from llm_module.parser import parse_instruction
#     from llm_module.schema import ParsedInstruction, ActionType, ConfidenceLevel
# """

# from .parser import parse_instruction
# from .schema import ParsedInstruction, ActionType, ConfidenceLevel

# __all__ = ["parse_instruction", "ParsedInstruction", "ActionType", "ConfidenceLevel"]

"""
llm_module
----------
Natural language instruction parser for the Multimodal LLM Industrial Task Planning project.
COS40005 Capstone — Swinburne University / ARENA2036

Public interface:
    from llm_module.parser import parse_instruction
    from llm_module.schema import ParsedInstruction, ActionType, ConfidenceLevel
"""

from .schema import ParsedInstruction, ActionType, ConfidenceLevel

# parser is imported lazily to avoid requiring OPENAI_API_KEY at import time
def parse_instruction(instruction: str, max_retries: int = 2):
    from .parser import parse_instruction as _parse
    return _parse(instruction, max_retries)

__all__ = ["parse_instruction", "ParsedInstruction", "ActionType", "ConfidenceLevel"]