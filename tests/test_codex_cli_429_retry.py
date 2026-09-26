"""PR-1b (#16): the 429-only retry / backoff policy in ``agents/codex_cli.py``.

Root cause this pins down: ``exit-criteria-trials`` really calls OpenRouter, so
a transient upstream 429 made ``codex_cli.generate_code`` blow up with
``KeyError: 'choices'`` and turned the merge run RED (run 36214248280), leaving
the merge gate at the provider's mercy. The fix retries **only** HTTP 429.

Three directions are locked here:

1. 429 then success  -> retries and returns the payload, with the expected
                        number of waits and a growing (8s, 16s) backoff;
2. persistent 429   -> exhausts RETRY_MAX_ATTEMPTS, then raises;
3. non-429 status   -> raises on the first response, zero retries, zero waits.

Plus the two budget rules: a ``Retry-After`` header is honoured, and a wait
that would not fit in RETRY_TOTAL_BUDGET aborts instead of sleeping past it.

All HTTP is mocked through ``httpx.MockTransport`` and ``codex_cli._sleep`` is
patched out, so the suite makes no network call and never actually waits.
"""

import asyncio

import httpx
import pytest

from agents import codex_cli


class _SleepRecorder:
    """Stand-in for ``codex_cli._sleep`` that records instead of waiting."""

    def __init__(self):
        self.delays: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=1.0)


def _ok(content: str = "print('hi')") -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"content": content}}]}
    )


def _rate_limited(retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    return httpx.Response(
        429, headers=headers, json={"error": {"message": "rate limited"}}
    )


def _post(handler, recorder, monkeypatch):
    """Drive ``_post_chat_completions`` against a mocked transport.

    Mirrors the production call site in ``generate_code``: the helper returns
    the non-429 response and the caller owns ``raise_for_status()``.
    """
    monkeypatch.setattr(codex_cli, "_sleep", recorder)

    async def run():
        async with _client(handler) as client:
            response = await codex_cli._post_chat_completions(
                client, headers={"Authorization": "Bearer test"}, payload={"model": "m"}
            )
            response.raise_for_status()
            return response

    return asyncio.run(run())


# --- direction 1: 429 then success ------------------------------------------


def test_429_then_success_retries_and_returns(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _rate_limited() if len(calls) <= 2 else _ok("print('hi')")

    recorder = _SleepRecorder()
    response = _post(handler, recorder, monkeypatch)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "print('hi')"
    # two 429s -> two retries -> three requests in total
    assert len(calls) == 3
    assert len(recorder.delays) == 2
    # exponential backoff: 8s then 16s, each within the jitter band
    assert recorder.delays[0] == pytest.approx(codex_cli.RETRY_BASE_DELAY, rel=0.26)
    assert recorder.delays[1] == pytest.approx(
        codex_cli.RETRY_BASE_DELAY * 2, rel=0.26
    )
    assert recorder.delays[1] > recorder.delays[0]
    assert sum(recorder.delays) <= codex_cli.RETRY_TOTAL_BUDGET


def test_generate_code_goes_through_the_retry_path(monkeypatch):
    """Wiring guard: ``generate_code`` must not fall back to a bare POST."""
    calls = []

    def handler(request):
        calls.append(request)
        return _rate_limited("1") if len(calls) == 1 else _ok("code()")

    recorder = _SleepRecorder()
    monkeypatch.setattr(codex_cli, "_sleep", recorder)
    monkeypatch.setattr(codex_cli, "OPENROUTER_API_KEY", "test-key")

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        codex_cli.httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_async_client(
            transport=httpx.MockTransport(handler), timeout=1.0
        ),
    )

    code = asyncio.run(codex_cli.generate_code("write code", system_prompt="sys"))

    assert code == "code()"
    assert len(calls) == 2
    # the Retry-After value is honoured exactly, not replaced by our backoff
    assert recorder.delays == [1.0]
    assert calls[0].headers["Authorization"] == "Bearer test-key"


# --- direction 2: persistent 429 --------------------------------------------


def test_persistent_429_exhausts_attempts_then_raises(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _rate_limited()

    recorder = _SleepRecorder()

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _post(handler, recorder, monkeypatch)

    assert excinfo.value.response.status_code == 429
    assert codex_cli.RETRY_MAX_ATTEMPTS == 4
    assert len(calls) == codex_cli.RETRY_MAX_ATTEMPTS
    assert len(recorder.delays) == codex_cli.RETRY_MAX_ATTEMPTS - 1
    # 8s -> 16s -> 32s, jittered, and inside the documented total budget
    assert recorder.delays[0] == pytest.approx(codex_cli.RETRY_BASE_DELAY, rel=0.26)
    assert recorder.delays[2] == pytest.approx(
        codex_cli.RETRY_BASE_DELAY * 4, rel=0.26
    )
    assert sum(recorder.delays) <= codex_cli.RETRY_TOTAL_BUDGET


# --- direction 3: non-429 is never retried ----------------------------------


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 500, 502, 503])
def test_non_429_status_raises_without_retry(monkeypatch, status):
    """Only 429 is retried; everything else fails fast on the first response."""
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": "nope"})

    recorder = _SleepRecorder()

    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        _post(handler, recorder, monkeypatch)

    assert excinfo.value.response.status_code == status
    assert len(calls) == 1
    assert recorder.delays == []


# --- Retry-After + total budget ---------------------------------------------


def test_retry_after_seconds_is_honoured(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _rate_limited("5")

    recorder = _SleepRecorder()

    with pytest.raises(httpx.HTTPStatusError):
        _post(handler, recorder, monkeypatch)

    assert len(calls) == codex_cli.RETRY_MAX_ATTEMPTS
    assert recorder.delays == [5.0] * (codex_cli.RETRY_MAX_ATTEMPTS - 1)


def test_retry_after_beyond_budget_aborts_without_waiting(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return _rate_limited(str(int(codex_cli.RETRY_TOTAL_BUDGET) + 600))

    recorder = _SleepRecorder()

    with pytest.raises(httpx.HTTPStatusError):
        _post(handler, recorder, monkeypatch)

    # no sleep at all: waiting would have blown the job's time budget
    assert len(calls) == 1
    assert recorder.delays == []


def test_retry_after_http_date_form_is_parsed():
    past = httpx.Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert codex_cli._retry_after_seconds(past) == 0.0
    assert codex_cli._retry_after_seconds(httpx.Response(429)) is None
    assert codex_cli._retry_after_seconds(
        httpx.Response(429, headers={"Retry-After": "not-a-date"})
    ) is None


def test_backoff_stays_within_jitter_band():
    for attempt in range(codex_cli.RETRY_MAX_ATTEMPTS - 1):
        base = codex_cli.RETRY_BASE_DELAY * (2 ** attempt)
        for _ in range(50):
            delay = codex_cli._backoff_delay(attempt)
            assert base * (1 - codex_cli.RETRY_JITTER_RATIO) <= delay <= base * (
                1 + codex_cli.RETRY_JITTER_RATIO
            )
