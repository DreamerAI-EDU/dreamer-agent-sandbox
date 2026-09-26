"""
Dreamer AI Phase 2 — Codex CLI
Real code generation via OpenRouter LLM API.
"""

import asyncio
import os
import logging
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

DEFAULT_MODEL = "deepseek/deepseek-chat"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.2
DEFAULT_TIMEOUT = 120.0

# --- HTTP 429 retry policy (PR-1b, closes #16) -------------------------------
# Only HTTP 429 (rate limited) is retried, and only to keep a transient
# upstream throttle from deciding the merge gate. Every other status — 4xx
# (400/401/402/403/404/…) and 5xx alike — is returned/raised on the first
# response, so a real bug is never masked by waiting.
#
# Time budget: a single call waits at most RETRY_TOTAL_BUDGET in total, and
# aborts early (raising the 429) rather than sleeping past it. Worst case wall
# clock is therefore
#     RETRY_MAX_ATTEMPTS * DEFAULT_TIMEOUT + RETRY_TOTAL_BUDGET
#     = 4 * 120s + 90s = 570s (~9.5 min)
# which stays well inside the CI job budget.
RETRY_MAX_ATTEMPTS = 4       # 1 initial attempt + 3 retries
RETRY_BASE_DELAY = 8.0       # seconds; doubles per retry: 8 -> 16 -> 32
RETRY_JITTER_RATIO = 0.25    # +/-25% jitter, to de-sync parallel clients
RETRY_TOTAL_BUDGET = 90.0    # ceiling for all waiting time within one call


def is_available() -> bool:
    """Check if OpenRouter API key is configured."""
    return bool(OPENROUTER_API_KEY)


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Parse a ``Retry-After`` header into a non-negative number of seconds.

    Accepts both RFC 7231 forms: a delta-seconds integer and an HTTP-date.
    Returns None when the header is absent or unparseable.
    """
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter for a 0-based retry index.

    base 8s doubling (8 -> 16 -> 32) with +/-RETRY_JITTER_RATIO jitter.
    """
    base = RETRY_BASE_DELAY * (2 ** attempt)
    jitter = base * RETRY_JITTER_RATIO * (2 * random.random() - 1)
    return max(0.0, base + jitter)


def _next_delay(attempt: int, retry_after: Optional[float]) -> float:
    """Wait time before retry number ``attempt`` (0-based).

    A server-supplied ``Retry-After`` wins over our own backoff and is honoured
    as-is; the total-budget check in the caller is what keeps it from blowing
    the job's time budget.
    """
    if retry_after is not None:
        return retry_after
    return _backoff_delay(attempt)


async def _sleep(seconds: float) -> None:
    """Indirection over ``asyncio.sleep`` so tests never really wait."""
    await asyncio.sleep(seconds)


async def _post_chat_completions(
    client: httpx.AsyncClient,
    *,
    headers: dict,
    payload: dict,
) -> httpx.Response:
    """POST ``/chat/completions``, retrying on HTTP 429 only.

    Returns the first response whose status is not 429; the caller still owns
    the ``raise_for_status()`` semantics for it.

    Raises:
        httpx.HTTPStatusError: when the attempts are exhausted, or when the
            next wait (including an honoured ``Retry-After``) would exceed
            RETRY_TOTAL_BUDGET — aborting beats sleeping past the budget.
    """
    url = f"{OPENROUTER_BASE_URL}/chat/completions"
    waited = 0.0
    attempts = 0
    response: Optional[httpx.Response] = None

    for attempt in range(RETRY_MAX_ATTEMPTS):
        response = await client.post(url, headers=headers, json=payload)
        attempts = attempt + 1
        if response.status_code != 429:
            return response
        if attempt == RETRY_MAX_ATTEMPTS - 1:
            break

        delay = _next_delay(attempt, _retry_after_seconds(response))
        if waited + delay > RETRY_TOTAL_BUDGET:
            logger.warning(
                "OpenRouter 429: next wait %.1fs would exceed the %.0fs "
                "retry budget (waited %.1fs, attempt %d/%d) — giving up",
                delay, RETRY_TOTAL_BUDGET, waited, attempt + 1,
                RETRY_MAX_ATTEMPTS,
            )
            break

        logger.warning(
            "OpenRouter 429 (attempt %d/%d) — retrying in %.1fs",
            attempt + 1, RETRY_MAX_ATTEMPTS, delay,
        )
        waited += delay
        await _sleep(delay)

    logger.error(
        "OpenRouter still rate limited (429) after %d attempt(s), %.1fs waited",
        attempts, waited,
    )
    raise httpx.HTTPStatusError(
        f"OpenRouter rate limited (429) after {attempts} attempt(s)",
        request=response.request,
        response=response,
    )


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
        httpx.HTTPError: On network or API-level errors. An HTTP 429 is retried
            (see the RETRY_* constants) and re-raised only once the attempts or
            the retry time budget are exhausted.
    """
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY environment variable not set")

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        response = await _post_chat_completions(
            client,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/DreamerAI-EDU/dreamer-agent-sandbox",
                "X-Title": "Dreamer AI Codex CLI",
            },
            payload={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]
