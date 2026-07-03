"""Minimal OpenRouter client using the OpenAI SDK.

OpenRouter is OpenAI-API-compatible, so we just point the OpenAI client at
OpenRouter's base URL and pass an OpenRouter API key.

Usage:
    python openrouter_client.py "Say hello in one sentence."
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.environ.get("OPENROUTER_API_KEY")
if not API_KEY:
    raise SystemExit("Missing OPENROUTER_API_KEY. Copy .env.example to .env and set your key.")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=API_KEY,
)

# Pick any model available on OpenRouter: https://openrouter.ai/models
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


def ask(prompt: str, model: str = DEFAULT_MODEL) -> str:
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return completion.choices[0].message.content


if __name__ == "__main__":
    user_prompt = " ".join(sys.argv[1:]) or "Say hello from OpenRouter in one sentence."
    print(ask(user_prompt))
