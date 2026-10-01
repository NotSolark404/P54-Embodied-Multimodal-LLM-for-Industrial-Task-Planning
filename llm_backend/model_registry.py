"""
model_registry.py
-----------------
Unified registry for all supported LLM models.
Each model is loaded from environment variables so no API key is
ever hardcoded. Add new models here without touching parser.py.

Supported models (configured via .env):
    OPENAI_API_KEY   + OPENAI_MODEL    -> GPT-4o (default: gpt-4o)
    GEMINI_API_KEY   + GEMINI_MODEL    -> Gemini (default: gemini-1.5-pro)
    DEEPSEEK_API_KEY + DEEPSEEK_MODEL  -> DeepSeek (default: deepseek-chat)

Usage:
    from model_registry import get_chain, AVAILABLE_MODELS
    chain = get_chain("openai")
    chain = get_chain("gemini")
    chain = get_chain("deepseek")
"""

import os
import logging
from typing import Literal

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain_openai import ChatOpenAI

from .schema import ParsedInstruction
from .prompts import build_system_prompt

load_dotenv()
logger = logging.getLogger(__name__)

ModelName = Literal["openai", "gemini", "deepseek"]

# ── All supported models ───────────────────────────────────────────────────────
AVAILABLE_MODELS: list[ModelName] = ["openai", "gemini", "deepseek"]

# ── Friendly display names for reports ────────────────────────────────────────
MODEL_DISPLAY_NAMES: dict[ModelName, str] = {
    "openai":   f"GPT-4o ({os.getenv('OPENAI_MODEL', 'gpt-4o')})",
    "gemini":   f"Gemini ({os.getenv('GEMINI_MODEL', 'gemini-1.5-pro')})",
    "deepseek": f"DeepSeek ({os.getenv('DEEPSEEK_MODEL', 'deepseek-chat')})",
}

# ── Shared prompt + output parser ─────────────────────────────────────────────
_output_parser = PydanticOutputParser(pydantic_object=ParsedInstruction)
_system_prompt  = build_system_prompt(
    format_instructions=_output_parser.get_format_instructions()
)
# _prompt_template = ChatPromptTemplate.from_messages([
#     ("system", _system_prompt),
#     ("human",  "Instruction: {instruction}"),
from langchain_core.prompts import SystemMessagePromptTemplate, HumanMessagePromptTemplate

_prompt_template = ChatPromptTemplate.from_messages([
    # Use template_format="mustache" or just escape the braces
    SystemMessagePromptTemplate.from_template(_system_prompt, template_format="mustache"),
    HumanMessagePromptTemplate.from_template("Instruction: {instruction}")

])


def _build_openai_llm():
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise EnvironmentError("OPENAI_API_KEY not set in .env")
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.0")),
        api_key=key,
    )


def _build_gemini_llm():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise EnvironmentError("GEMINI_API_KEY not set in .env")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "Install langchain-google-genai: pip install langchain-google-genai"
        )
    return ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-1.5-pro"),
        temperature=float(os.getenv("GEMINI_TEMPERATURE", "0.0")),
        google_api_key=key,
        convert_system_message_to_human=True,
    )


def _build_deepseek_llm():
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise EnvironmentError("DEEPSEEK_API_KEY not set in .env")
    # DeepSeek exposes an OpenAI-compatible API endpoint
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.0")),
        api_key=key,
        base_url="https://api.deepseek.com/v1",
    )


_BUILDERS = {
    "openai":   _build_openai_llm,
    "gemini":   _build_gemini_llm,
    "deepseek": _build_deepseek_llm,
}


def get_chain(model_name: ModelName):
    """
    Build and return a LangChain chain for the requested model.
    The chain accepts {"instruction": str} and returns a ParsedInstruction.

    Args:
        model_name: One of "openai", "gemini", "deepseek"

    Returns:
        A runnable LangChain chain.

    Raises:
        ValueError:        If model_name is not recognised.
        EnvironmentError:  If the required API key is missing from .env.
        ImportError:       If a required package is not installed.
    """
    if model_name not in _BUILDERS:
        raise ValueError(
            f"Unknown model '{model_name}'. Choose from: {AVAILABLE_MODELS}"
        )
    logger.debug(f"Building chain for model: {model_name}")
    llm = _BUILDERS[model_name]()
    return _prompt_template | llm | _output_parser


def get_available_models() -> list[ModelName]:
    """
    Return only the models whose API keys are present in the environment.
    Safe to call without raising — models with missing keys are silently skipped.
    """
    key_map = {
        "openai":   "OPENAI_API_KEY",
        "gemini":   "GEMINI_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
    }
    return [m for m in AVAILABLE_MODELS if os.getenv(key_map[m])]