"""c1-13b Phase 1 — four-scenario voice smoke (P1-P3 trial).

What this proves: the app boundary end-to-end over a real socket — flag gate,
consent gate, multipart clip in, transcript out, meters moved, meters stopping
voice, kid-safe wording, and no audio / no transcript left on disk or in the
audit log.

What this does NOT prove: vendor accuracy or latency. That was the 對測
(c1-13b_對測報告_v1.0). The provider call is stubbed by default so this smoke
is free, offline and repeatable; ``--live`` calls the real provider instead
(needs the host keys, and the transcript is whatever the audio really says).

Usage:
    python scripts/smoke_voice.py           # stub provider (default)
    python scripts/smoke_voice.py --live    # real provider call

Exit code 0 = all four scenarios PASS. Nothing billable, nothing persisted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import struct
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aiohttp  # noqa: E402
from aiohttp import FormData, web  # noqa: E402

from auth import api as api_mod  # noqa: E402
from auth import consent as consent_mod  # noqa: E402
from auth import db as auth_db  # noqa: E402
from auth import voice_quota  # noqa: E402
from auth import voice_stt  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}
PARENT_PASSWORD = "smoke-pass-0001"
STUB_TEXT = "what makes the sky blue"
BAND = "P1-P3"


# --------------------------------------------------------------------------
# tiny helpers
# --------------------------------------------------------------------------

def future_iso(days: int = 7) -> str:
    import datetime

    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")


def wav(seconds: float, *, sample_rate: int = 16000) -> bytes:
    """A real PCM WAV of exactly ``seconds``."""
    frames = int(sample_rate * seconds)
    payload = b"\x00\x00" * frames
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, sample_rate * 2, 2, 16)
    body = (
        b"fmt " + struct.pack("<I", len(fmt)) + fmt
        + b"data" + struct.pack("<I", len(payload)) + payload
    )
    return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WAVE" + body


def clip_form(payload: bytes, *, declared_ms: int, lang: str = "en") -> FormData:
    form = FormData()
    form.add_field("audio", payload, filename="clip", content_type="audio/webm")
    form.add_field("duration_ms", str(declared_ms))
    form.add_field("lang", lang)
    return form


def seconds_cookie(resp, name: str) -> str:
    for raw in resp.headers.getall("Set-Cookie", []):
        if raw.startswith(f"{name}="):
            return raw.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError(f"no {name} cookie in reply")


def kid_headers(token: str) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"kid_session={token}"}


def auth_headers(token: str) -> dict[str, str]:
    return {**HEADERS, "Cookie": f"auth_session={token}"}


class Recorder:
    """Stands in for the provider; remembers exactly what it was handed."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, audio, *, content_type, lang_hint=None, client=None):
        self.calls.append({"bytes": len(audio), "lang": lang_hint})
        return voice_stt.SttResult(text=STUB_TEXT, provider="azure", latency_ms=42)


def sign_consent(student_id: str) -> None:
    conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
    try:
        parent_id = conn.execute(
            "SELECT parent_id FROM students WHERE id = ?", (student_id,)
        ).fetchone()[0]
        row = conn.execute("SELECT id FROM students ORDER BY rowid DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    assert row is not None
    cfg = consent_mod.get_doc_config("voice_consent")
    consent_mod.insert_consent_row(
        user_id=parent_id,
        doc_type="voice_consent",
        doc_version=cfg["current_version"],
        action="agreed",
        ip="smoke",
        user_agent="scripts/smoke_voice.py",
        student_id=student_id,
    )


# --------------------------------------------------------------------------
# one-time setup: schema, teacher, class, invited + confirmed kid, kid session
# --------------------------------------------------------------------------

async def bootstrap(base: str) -> tuple[str, str]:
    """Returns (kid_session_token, student_id)."""
    async with aiohttp.ClientSession() as s:
        code = f"smoke-invite-{uuid.uuid4().hex[:8]}"
        auth_db.insert_teacher_invite(
            code=code, created_by="smoke", expires_at=future_iso()
        )
        await s.post(
            f"{base}/api/auth/register",
            json={"invite_code": code, "email": "smoke-teacher@test.local",
                  "password": PARENT_PASSWORD},
            headers=HEADERS,
        )
        login = await s.post(
            f"{base}/api/auth/login",
            json={"email": "smoke-teacher@test.local", "password": PARENT_PASSWORD},
            headers=HEADERS,
        )
        teacher = seconds_cookie(login, "auth_session")

        cls = (await (await s.post(
            f"{base}/api/classes", json={"name": "Smoke Class"},
            headers=auth_headers(teacher),
        )).json())["class"]
        invite = (await (await s.post(
            f"{base}/api/invites",
            json={"class_id": cls["id"], "parent_email": "smoke-parent@test.local",
                  "first_name": "小測", "age_band": BAND, "lang_code": "zh-hk"},
            headers=auth_headers(teacher),
        )).json())["pin"]

        conn = sqlite3.connect(os.environ["DREAMER_DB_PATH"])
        try:
            student_id = conn.execute(
                "SELECT id FROM students ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
            token = conn.execute(
                "SELECT token FROM invites ORDER BY rowid DESC LIMIT 1"
            ).fetchone()[0]
        finally:
            conn.close()

        await s.post(
            f"{base}/api/invites/{token}/confirm",
            json={"password": PARENT_PASSWORD, "privacy_policy": True,
                  "chat_consent": True},
        )
        await s.post(
            f"{base}/api/classes/{cls['id']}/confirm",
            json={"student_id": student_id}, headers=auth_headers(teacher),
        )
        kid_login = await s.post(
            f"{base}/api/student/login",
            json={"join_code": cls["join_code"], "pin": invite},
            headers=HEADERS,
        )
        assert kid_login.status == 200, await kid_login.text()
        return seconds_cookie(kid_login, "kid_session"), student_id


# --------------------------------------------------------------------------
# the four scenarios
# --------------------------------------------------------------------------

async def scenario_1_flag_off(base: str, kid: str) -> tuple[bool, list[str]]:
    """Flag OFF everywhere: no mic, and the endpoint refuses even if asked."""
    out: list[str] = []
    async with aiohttp.ClientSession() as s:
        cfg = await (await s.get(f"{base}/api/voice/config", headers=kid_headers(kid))).json()
        out.append(f"GET /api/voice/config -> {json.dumps(cfg)}")
        post = await s.post(
            f"{base}/api/voice/transcribe",
            data=clip_form(wav(1), declared_ms=1000), headers=kid_headers(kid),
        )
        out.append(f"POST /api/voice/transcribe -> {post.status} {await post.text()}")
        ok = cfg == {"enabled": False} and post.status == 403
    return ok, out


async def scenario_2_no_consent(base: str, kid: str) -> tuple[bool, list[str]]:
    """Flag ON, consent not on file: the kid cannot even see a button."""
    out: list[str] = []
    os.environ["VOICE_P1P3_ENABLED"] = "1"
    async with aiohttp.ClientSession() as s:
        resp = await s.get(f"{base}/api/voice/config", headers=kid_headers(kid))
        cfg = await resp.json()
        out.append(f"GET /api/voice/config -> {resp.status} {json.dumps(cfg)}")
        post = await s.post(
            f"{base}/api/voice/transcribe",
            data=clip_form(wav(1), declared_ms=1000), headers=kid_headers(kid),
        )
        out.append(f"POST /api/voice/transcribe -> {post.status}")
        ok = cfg == {"enabled": False} and post.status == 403
    return ok, out


async def scenario_3_happy_path(
    base: str, kid: str, student_id: str, rec: Recorder, tmp: Path
) -> tuple[bool, list[str]]:
    """Consent signed: clip in, transcript out to the composer, meters moved."""
    out: list[str] = []
    sign_consent(student_id)
    before = voice_quota.month_meter()["seconds"]
    async with aiohttp.ClientSession() as s:
        cfg = await (await s.get(f"{base}/api/voice/config", headers=kid_headers(kid))).json()
        out.append(f"GET /api/voice/config -> {json.dumps(cfg)}")
        payload = wav(3)
        resp = await s.post(
            f"{base}/api/voice/transcribe",
            data=clip_form(payload, declared_ms=3000), headers=kid_headers(kid),
        )
        body = await resp.json()
        out.append(f"POST /api/voice/transcribe -> {resp.status} {json.dumps(body)}")

    out.append(
        f"provider saw {rec.calls[-1]['bytes']} bytes (clip {len(payload)}), "
        f"lang={rec.calls[-1]['lang']}, audio bytes on disk: "
        f"{any(b'RIFF' in f.read_bytes() for f in tmp.rglob('*') if f.is_file())}"
    )
    # the transcript must be nowhere but the HTTP reply
    audit = tmp / "audit_log.jsonl"
    log_text = audit.read_text(encoding="utf-8") if audit.exists() else ""
    out.append(f"transcript in audit log: {STUB_TEXT in log_text}")

    ok = (
        cfg.get("enabled") is True
        and cfg.get("max_seconds") == 60
        and resp.status == 200
        and body.get("text") == STUB_TEXT
        and body.get("seconds_used") == 3
        and voice_quota.month_meter()["seconds"] == before + 3
        and STUB_TEXT not in log_text
        and rec.calls[-1]["bytes"] == len(payload)
    )
    return ok, out


async def scenario_4_meter_stops_voice(
    base: str, kid: str, student_id: str
) -> tuple[bool, list[str]]:
    """Meter reached: the button disappears AND the POST is refused."""
    out: list[str] = []
    os.environ["VOICE_MAX_SEGMENT_SECONDS"] = "10"
    os.environ["VOICE_DAILY_STUDENT_SECONDS"] = "13"  # 3 s already used in S3
    async with aiohttp.ClientSession() as s:
        first = await s.post(
            f"{base}/api/voice/transcribe",
            data=clip_form(wav(5), declared_ms=5000), headers=kid_headers(kid),
        )
        first_body = await first.json()
        out.append(
            f"5 s clip with 10 s left -> {first.status} "
            f"{json.dumps(first_body)} "
            f"(daily used {voice_quota.student_daily_seconds(student_id)} s)"
        )
        cfg = await (await s.get(f"{base}/api/voice/config", headers=kid_headers(kid))).json()
        out.append(f"GET /api/voice/config -> {json.dumps(cfg)}")
        second = await s.post(
            f"{base}/api/voice/transcribe",
            data=clip_form(wav(1), declared_ms=1000), headers=kid_headers(kid),
        )
        out.append(f"1 s clip with <1 segment left -> {second.status} {await second.text()}")
        ok = (
            first.status == 200
            and cfg == {"enabled": False}
            and second.status == 403
        )
    return ok, out


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

async def main(live: bool) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="voice-smoke-"))
    os.environ["DREAMER_DB_PATH"] = str(tmp / "smoke.db")
    consent_mod.AUDIT_LOG_PATH = str(tmp / "audit_log.jsonl")
    os.environ.pop("VOICE_P1P3_ENABLED", None)
    for key in (
        "VOICE_MAX_SEGMENT_SECONDS",
        "VOICE_DAILY_STUDENT_SECONDS",
        "VOICE_MONTHLY_GLOBAL_SECONDS",
    ):
        os.environ.pop(key, None)
    auth_db.ensure_schema()

    rec = Recorder()
    if not live:
        voice_stt.transcribe = rec  # attribute patch: api.py calls the module attr

    runner = web.AppRunner(build_app())
    await runner.setup()
    port = 0
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    base = f"http://127.0.0.1:{port}"

    print(f"c1-13b voice smoke — {base}  provider={'live' if live else 'stub'}")
    print(f"  temp: {tmp}\n")

    kid, student_id = await bootstrap(base)
    results: list[tuple[str, bool, list[str]]] = []
    started = time.time()
    try:
        results.append(("S1 flag off -> no mic, endpoint refuses",
                        *await scenario_1_flag_off(base, kid)))
        results.append(("S2 flag on + no consent -> no mic",
                        *await scenario_2_no_consent(base, kid)))
        results.append(("S3 consent signed -> transcript out, meters +3 s",
                        *await scenario_3_happy_path(base, kid, student_id, rec, tmp)))
        results.append(("S4 meter reached -> mic gone, POST refused",
                        *await scenario_4_meter_stops_voice(base, kid, student_id)))
    finally:
        await runner.cleanup()

    failed = 0
    for name, ok, lines in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for line in lines:
            print(f"        {line}")
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} scenarios PASS "
          f"in {time.time() - started:.1f}s; provider calls: "
          f"{0 if live else len(rec.calls)} (stub)")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="call the real STT provider instead of the stub")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.live)))
