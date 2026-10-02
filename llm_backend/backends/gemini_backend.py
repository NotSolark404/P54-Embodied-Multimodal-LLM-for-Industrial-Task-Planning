"""
backends/gemini_backend.py
--------------------------
Initialises a LangChain-compatible LLM using the Google Gemini API.

Required env vars (in .env):
    GEMINI_API_KEY      -- your Google AI Studio API key
    GEMINI_MODEL        -- model name (default: gemini-1.5-flash)
    GEMINI_TEMPERATURE  -- sampling temperature (default: 0.0)

Note:
    Valid model strings as of April 2026:
        gemini-1.5-flash, gemini-1.5-pro, gemini-2.0-flash
    "gemini-3-flash-preview" does NOT exist yet -- will return a 404.
"""

import os
import logging

logger = logging.getLogger(__name__)


def build_llm():
    """Return an initialised ChatGoogleGenerativeAI instance."""
    api_key = os.getenv("GEMINI_API_KEY")
    model   = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    temp    = float(os.getenv("GEMINI_TEMPERATURE", "0.0"))

    # Key first, SDK second — see openai_backend.py for why.
    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not found. Add it to your .env file."
        )

    from langchain_google_genai import ChatGoogleGenerativeAI

    logger.info(f"[Gemini backend] model={model}, temperature={temp}")
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temp,
        google_api_key=api_key,
    )