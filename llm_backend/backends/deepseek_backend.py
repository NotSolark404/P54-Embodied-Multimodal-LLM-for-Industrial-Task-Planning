"""
backends/deepseek_backend.py
----------------------------
Initialises a LangChain-compatible LLM using the native ChatDeepSeek class
from the langchain-deepseek package.

Install:
    pip install langchain-deepseek

Required env vars (in .env):
    DEEPSEEK_API_KEY     -- your DeepSeek API key from platform.deepseek.com
    DEEPSEEK_MODEL       -- model name (default: deepseek-chat)
    DEEPSEEK_TEMPERATURE -- sampling temperature (default: 0.0)

Model options:
    deepseek-chat        -- DeepSeek V3.2, general purpose, supports structured
                            output and tool use. USE THIS for the parser.
    deepseek-reasoner    -- DeepSeek V3.2 thinking mode (chain-of-thought).
                            Does NOT support structured output / tool calling.
                            Do not use with the parser.

Free tier:
    New accounts receive 5 million free tokens (no credit card required).
    Credits are valid for 30 days from registration.
    No enforced rate limits -- all requests served on a best-effort basis.
    Sign up at: https://platform.deepseek.com
"""

import os
import logging

logger = logging.getLogger(__name__)


def build_llm():
    """Return an initialised ChatDeepSeek instance."""
    api_key = os.getenv("DEEPSEEK_API_KEY")
    model   = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    temp    = float(os.getenv("DEEPSEEK_TEMPERATURE", "0.0"))

    # Key first, SDK second — see openai_backend.py for why.
    if not api_key:
        raise EnvironmentError(
            "DEEPSEEK_API_KEY not found. "
            "Sign up at platform.deepseek.com and add the key to your .env file."
        )

    from langchain_deepseek import ChatDeepSeek

    if model == "deepseek-reasoner":
        logger.warning(
            "[DeepSeek backend] deepseek-reasoner does not support structured "
            "output. The parser may fail. Use deepseek-chat instead."
        )

    logger.info(f"[DeepSeek backend] model={model}, temperature={temp}")
    return ChatDeepSeek(
        model=model,
        temperature=temp,
        api_key=api_key,
    )