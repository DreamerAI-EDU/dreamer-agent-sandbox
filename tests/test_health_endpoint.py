"""Gate-B leg ③ — /health and /api/health probe contract.

Why these cases exist (they are the acceptance criteria, not decoration):

* both paths answer 200 with a machine-readable body, so Caddy (``/api/*``)
  and the in-container Docker HEALTHCHECK (``/health`` on 127.0.0.1:8000)
  can both use them;
* the probe is anonymous — no session cookie, no CSRF header — because a
  probe has neither;
* when the auth DB is unreachable the endpoint goes 503 / ``degraded``, so a
  container that is "up" with a locked DB no longer reads as green;
* the body never leaks a filesystem path, a row, or an exception string,
  since /health may be reachable from the public origin.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

PROBE_SCRIPT = os.path.join(REPO_ROOT, "scripts", "health_probe.py")

from auth import api as auth_api  # noqa: E402
from auth.api import build_app  # noqa: E402

PROBE_PATHS = ("/health", "/api/health")


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Fresh app + fresh SQLite DB per test (DREAMER_DB_PATH isolated)."""
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "auth_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PROBE_PATHS)
async def test_probe_is_green_without_any_credential(client, path):
    """A probe carries no cookie and no CSRF header — and still gets 200."""
    resp = await client.get(path)
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "dreamer-api"
    assert body["checks"] == {"db": "ok"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PROBE_PATHS)
async def test_probe_body_leaks_no_path_or_detail(client, path):
    """Public-origin safe: no DB path, no exception text, no row data."""
    resp = await client.get(path)
    raw = await resp.text()
    for forbidden in (".db", "dreamer.db", "/var/lib", "Traceback", "sqlite"):
        assert forbidden not in raw, f"{path} body leaks {forbidden!r}"
    assert set((await resp.json()).keys()) == {"status", "service", "checks"}


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PROBE_PATHS)
async def test_probe_goes_503_when_db_is_unreachable(client, path, monkeypatch):
    """Container up + DB dead must NOT read as green."""

    def _boom():
        raise RuntimeError("db locked: /secret/path/should-not-leak.db")

    monkeypatch.setattr(auth_api.db, "connect", _boom)
    resp = await client.get(path)
    assert resp.status == 503
    body = await resp.json()
    assert body["status"] == "degraded"
    assert body["checks"] == {"db": "fail"}
    raw = await resp.text()
    assert "should-not-leak" not in raw
    assert "Traceback" not in raw


@pytest.mark.asyncio
async def test_probe_never_raises_into_aiohttp(client, monkeypatch):
    """Probe must swallow its own failure — no 500, no handler traceback."""

    def _boom():
        raise Exception("any failure")

    monkeypatch.setattr(auth_api.db, "connect", _boom)
    resp = await client.get("/health")
    assert resp.status == 503


@pytest.mark.asyncio
async def test_probe_is_not_a_shortcut_around_the_auth_guard(client):
    """Login-gated surfaces still 401 — the probe does not open anything."""
    resp = await client.get("/api/auth/me")
    assert resp.status == 401


def _run_probe(url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROBE_SCRIPT), "--url", url, "--timeout", "3"],
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.asyncio
async def test_container_probe_exits_zero_against_a_live_app(client):
    """The Dockerfile HEALTHCHECK script must agree with the endpoint.

    ``to_thread`` matters: a blocking subprocess.run inside the loop would
    starve the in-process TestServer and the probe would time out against
    its own app (false red).
    """
    port = client.server.port
    result = await asyncio.to_thread(_run_probe, f"http://127.0.0.1:{port}/health")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HEALTHY" in result.stdout


@pytest.mark.asyncio
async def test_container_probe_exits_one_when_app_is_gone():
    """A dead port must fail loudly, without a traceback on stdout."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    result = _run_probe(f"http://127.0.0.1:{dead_port}/health")
    assert result.returncode == 1
    assert "UNHEALTHY" in result.stdout
    assert "Traceback" not in result.stdout + result.stderr
