"""
backends/openai_backend.py
--------------------------
Initialises a LangChain-compatible LLM using the OpenAI API (GPT-4o by default).

Required env vars (in .env):
    OPENAI_API_KEY      -- your OpenAI secret key
    OPENAI_MODEL        -- model name (default: gpt-4o)
    OPENAI_TEMPERATURE  -- sampling temperature (default: 0.0)
"""

import os
import logging

logger = logging.getLogger(__name__)


def build_llm():
    """Return an initialised ChatOpenAI instance."""
    api_key = os.getenv("OPENAI_API_KEY")
    model   = os.getenv("OPENAI_MODEL", "gpt-4o")
    temp    = float(os.getenv("OPENAI_TEMPERATURE", "0.0"))

    # The key is checked before the SDK is imported. With the import first, a
    # machine that has not installed this optional backend reported
    # ModuleNotFoundError for a problem that was really a missing key, and the
    # EnvironmentError below was unreachable.
    if not api_key:
        raise EnvironmentError(
            "OPENAI_API_KEY not found. "
            "Copy .env.example to .env and add your key."
        )

    from langchain_openai import ChatOpenAI

    logger.info(f"[OpenAI backend] model={model}, temperature={temp}")
    return ChatOpenAI(
        model=model,
        temperature=temp,
        api_key=api_key,
    )