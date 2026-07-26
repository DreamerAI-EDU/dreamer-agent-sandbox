"""
Dreamer AI Phase 2 — Codex CLI
Real code generation via OpenRouter LLM API.
"""

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MODEL = "google/gemini-2.5-flash"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 120.0


def is_available() -> bool:
    """Check if OpenRouter API key is configured."""
    return bool(OPENROUTER_API_KEY)


async def generate_code(
    prompt: str,
    *,
    system_prompt: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    """Call OpenRouter API to generate code from a prompt.

    Args:
        prompt: The user prompt describing what code to generate.
        system_prompt: Optional system-level instruction.
        model: OpenRouter model identifier.
        temperature: Sampling temperature (0.0 = deterministic).
        max_tokens: Maximum tokens in the response.

    Returns:
        Generated code as a string.

    Raises:
        RuntimeError: If OPENROUTER_API_KEY is not set.
        httpx.HTTPError: On network or API-level errors.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await client.post(
            f"{OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/DreamerAI-EDU/dreamer-agent-sandbox",
                "X-Title": "Dreamer AI Codex CLI",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
