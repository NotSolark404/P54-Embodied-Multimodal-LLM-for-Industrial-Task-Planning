"""
hello_world.py
--------------
Basic connection test for the LLM module.
Run this first to confirm your API key and setup are working
before running the full parser.

Usage:
    python hello_world.py
"""

import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

load_dotenv()

def main():
    api_key = os.getenv("OPENAI_API_KEY")
    model   = os.getenv("OPENAI_MODEL", "gpt-4o")

    if not api_key or api_key == "sk-your-api-key-here":
        print("OPENAI_API_KEY not set.")
        print("Copy .env.example → .env and add your real API key.")
        return

    print(f"API key loaded: {api_key[:8]}...{api_key[-4:]}")
    print(f"Model: {model}")
    print("Sending test message to OpenAI...\n")

    try:
        llm = ChatOpenAI(model=model, temperature=0.0, api_key=api_key)
        response = llm.invoke([
            HumanMessage(content=(
                "You are a robot assistant. "
                "Reply with exactly one sentence confirming you are ready."
            ))
        ])
        print(f"Response: {response.content}")
        print("\nConnection successful! You're ready to use the LLM module.")

    except Exception as e:
        print(f"Connection failed: {e}")
        print("heck your API key and internet connection.")

if __name__ == "__main__":
    main()