"""
schema.py
---------
Pydantic schema for the structured output returned by the LLM instruction parser.
All other modules (scene representation, task planner) should import from here
to ensure a consistent interface contract.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class ActionType(str, Enum):
    PICK = "pick"
    PLACE = "place"
    MOVE = "move"
    LOCATE = "locate"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ParsedInstruction(BaseModel):
    """
    Structured output from the LLM instruction parser.

    Example:
        Instruction: "pick up the red block and place it in the left tray"
        Output:
            action="pick", object_target="red block",
            destination="left tray", spatial_relation="in",
            confidence="high", raw_instruction="pick up the red block..."
    """

    action: ActionType = Field(
        description="The primary robot action to perform."
    )
    object_target: str = Field(
        description="The object the action applies to (e.g. 'red block', 'blue cube')."
    )
    destination: Optional[str] = Field(
        default=None,
        description="Where the object should go, if applicable (e.g. 'left tray', 'workstation A')."
    )
    spatial_relation: Optional[str] = Field(
        default=None,
        description="Spatial relationship described (e.g. 'left of', 'near', 'on top of')."
    )
    confidence: ConfidenceLevel = Field(
        description="How confident the parser is in this interpretation."
    )
    raw_instruction: str = Field(
        description="The original instruction string, preserved for logging and debugging."
    )
    notes: Optional[str] = Field(
        default=None,
        description="Any ambiguities, warnings, or clarifications the LLM flagged."
    )