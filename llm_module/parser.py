"""
parser.py
---------
LLM instruction parser using LangChain + GPT-4o.
Converts natural language robot instructions into structured JSON
conforming to the ParsedInstruction schema.
"""

import os
import json
import logging
from dotenv import load_dotenv

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.exceptions import OutputParserException

from schema import ParsedInstruction

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Environment ───────────────────────────────────────────────────────────────
load_dotenv()

OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4o")
TEMPERATURE     = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))

if not OPENAI_API_KEY:
    raise EnvironmentError(
        "OPENAI_API_KEY not found. "
        "Copy .env.example to .env and add your key."
    )

# ── System prompt ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """
You are an instruction parser for an intelligent industrial robot operating in a simulated workspace.

Your job is to read a natural language task instruction and extract structured information from it.

The robot can perform the following actions ONLY: pick, place, move, locate.
Objects in the workspace include coloured blocks (red, blue, green, yellow) and locations such as trays and workstations.

Rules:
- Always return valid JSON matching the schema exactly.
- If the instruction is ambiguous or unclear, set confidence to "low" and explain in the notes field.
- If an action is not in the allowed list, map it to the closest valid action.
- If no destination is mentioned, leave destination as null.
- If no spatial relation is mentioned, leave spatial_relation as null.
- Never invent objects or locations not mentioned in the instruction.
- Preserve the original instruction in raw_instruction exactly as given.

{format_instructions}
"""

USER_PROMPT = "Instruction: {instruction}"

# ── Parser setup ──────────────────────────────────────────────────────────────
output_parser = PydanticOutputParser(pydantic_object=ParsedInstruction)

prompt = ChatPromptTemplate.from_messages([
    ("system", SYSTEM_PROMPT),
    ("human",  USER_PROMPT),
]).partial(format_instructions=output_parser.get_format_instructions())

llm = ChatOpenAI(
    model=OPENAI_MODEL,
    temperature=TEMPERATURE,
    api_key=OPENAI_API_KEY,
)

chain = prompt | llm | output_parser

# ── Public interface ──────────────────────────────────────────────────────────
def parse_instruction(instruction: str, max_retries: int = 2) -> ParsedInstruction:
    """
    Parse a natural language robot instruction into a structured ParsedInstruction.

    Args:
        instruction: Plain English task instruction from the user.
        max_retries:  Number of times to retry on JSON parse failure.

    Returns:
        ParsedInstruction: Validated structured output.

    Raises:
        ValueError: If parsing fails after all retries.

    Example:
        >>> result = parse_instruction("pick up the red block")
        >>> print(result.action)   # ActionType.PICK
        >>> print(result.object_target)  # "red block"
    """
    if not instruction or not instruction.strip():
        raise ValueError("Instruction cannot be empty.")

    instruction = instruction.strip()
    logger.info(f"Parsing instruction: '{instruction}'")

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            result = chain.invoke({"instruction": instruction})
            logger.info(f"Parsed successfully on attempt {attempt}: {result}")
            return result

        except OutputParserException as e:
            last_error = e
            logger.warning(f"Attempt {attempt} failed (OutputParserException): {e}")

        except Exception as e:
            last_error = e
            logger.warning(f"Attempt {attempt} failed ({type(e).__name__}): {e}")

    raise ValueError(
        f"Failed to parse instruction after {max_retries} attempts. "
        f"Last error: {last_error}"
    )