"""W4 PR-A API tests — Portfolio surfaces (kid view / parent view / share_card).

Covers the step-1 backend checklist per W4 instruction (PR-A):
  * kid surface: parent session acting for the unlocked child only; the kid
    surface carries NO student id and NO share_card payload (R2)
  * role gates: teacher/admin -> unified 403 (kid AND parent surfaces), the
    teacher view is out of W4 scope
  * unified 403 discipline: cross-child / unknown id / unknown item all 403
    (no existence oracle); ambiguous mask -> 400; missing param -> 400
  * parent surface: masked student id (W3-B convention), display_name =
    first_name only (B24), media_consent indicator, items + one share_card
    per item in the same order
  * share_card whitelist: exact 8-field set (R3, docs/phase6-schemas.md §2)
  * P-series red line: internal_label / confidence / rubric_id / student
    full id never leave the server on ANY surface
  * R3 same-source parity: API share_card == PortfolioAgent._build_share_card
"""

from __future__ import annotations

import datetime
import json
import os
import sqlite3
import uuid

import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("PYTHONPATH", REPO_ROOT)

from auth import db as auth_db  # noqa: E402
from auth.api import build_app  # noqa: E402

HEADERS = {"X-Requested-With": "XMLHttpRequest"}

# Fixed identities across the seeded world
P1 = "user-p1"          # parent of students A and A2
P2 = "user-p2"          # parent of student D (empty portfolio; withdrawn)
T1 = "user-t1"          # teacher (must never reach portfolio surfaces)
SID_A = "aaaa1111aaaa2222"   # parent P1; agreed consent; 2 manual items
SID_A2 = "bbbb1111cccc2222"  # parent P1; empty portfolio (distinct prefix)
SID_A3 = "bbbb1111dddd2222"  # parent P1; shares SID_A2 prefix -> ambiguity
SID_D = "dddd1111dddd2222"   # parent P2; withdrawn consent; empty -> parity seed

# The exact whitelist consumed by W4 renderers (R3; mirrors
# agents.portfolio_agent.SHARE_CARD_WHITELIST — keep in lock-step).
SHARE_CARD_WHITELIST = {
    "display_name", "item_id", "title", "artifact_summary",
    "competencies_4d", "kid_label", "brand", "generated_at",
}

PORTFOLIO_DDL = """
CREATE TABLE IF NOT EXISTS portfolio_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL UNIQUE,
    student_id TEXT NOT NULL,
    topic_id TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    evidence_excerpt TEXT NOT NULL DEFAULT '',
    competencies_4d TEXT NOT NULL DEFAULT '[]',
    growth_note TEXT NOT NULL DEFAULT '',
    kid_label TEXT NOT NULL DEFAULT '',
    internal_label TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.0,
    rubric_id TEXT NOT NULL DEFAULT '',
    achieved_at TEXT NOT NULL,
    linked_project_id TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_portfolio_student
    ON portfolio_items(student_id, achieved_at);
CREATE TABLE IF NOT EXISTS assessment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en', internal_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0, rubric_id TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '', agent_used TEXT NOT NULL DEFAULT 'assessment',
    cost_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_logs_student ON assessment_logs(student_id, created_at);
"""


def _future_iso(days: int = 7) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
    ).isoformat().replace("+00:00", "Z")


def _ago_iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        - datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _cookie_header(user_id: str) -> dict:
    sid = "ses-pf-" + uuid.uuid4().hex[:8]
    auth_db.create_session(session_id=sid, user_id=user_id, expires_at=_future_iso())
    return {"Cookie": f"auth_session={sid}", **HEADERS}


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DREAMER_DB_PATH", str(tmp_path / "pf_test.db"))
    app = build_app()
    async with TestClient(TestServer(app)) as c:
        yield c


@pytest_asyncio.fixture
async def world(client, tmp_path, monkeypatch):
    """Fresh DB seeded with users/students + portfolio items + one log."""
    monkeypatch.setattr("auth.consent.AUDIT_LOG_PATH", str(tmp_path / "audit.log"))
    db_path = auth_db._db_path()
    auth_db.ensure_schema()
    auth_db.apply_class_meta_migration()
    for uid, role in ((P1, "parent"), (P2, "parent"), (T1, "teacher")):
        auth_db.create_user(
            user_id=uid,
            email=f"{uid}@test.local",
            password_hash="test-pass-w4-pf-001",
            role=role,
            email_verified=True,
        )

    conn = sqlite3.connect(db_path)
    conn.executescript(PORTFOLIO_DDL)
    cur = conn.cursor()
    students = [
        (SID_A, P1, "阿明", "P4-P6", "zh-hk"),
        (SID_A2, P1, "小晴", "P4-P6", "zh-hk"),
        (SID_A3, P1, "小樂", "P4-P6", "zh-hk"),
        (SID_D, P2, "家豪", "P4-P6", "zh-hk"),
    ]
    for sid, parent, fname, band, lang in students:
        cur.execute(
            "INSERT INTO students (id,parent_id,teacher_id,first_name,age_band,"
            "lang_code,pin_hash,pin_lock_until,failed_pin_count,created_at) "
            "VALUES (?,?,NULL,?,?,?,'x',NULL,0,?)",
            (sid, parent, fname, band, lang, _ago_iso(days=90)),
        )
    # consent rows
    cur.execute(
        "INSERT INTO consent_log (user_id,doc_type,doc_version,action,student_id,"
        "created_at) VALUES (?, 'media_consent','2026-01','agreed',?,?)",
        (P1, SID_A, _ago_iso(days=30)),
    )
    cur.execute(
        "INSERT INTO consent_log (user_id,doc_type,doc_version,action,student_id,"
        "created_at) VALUES (?, 'media_consent','2026-01','withdrawn',?,?)",
        (P2, SID_D, _ago_iso(days=20)),
    )
    # Two manual showcase items for student A (newest first on the API).
    # Text is deliberately neutral so the P-series negative scan stays clean.
    manual_items = [
        (
            "pf-manual-1001", "maths-multiplication-01", "乘法小挑戰",
            "設計咗一個乘法口訣挑戰，答啱全部關卡。",
            "自己出題考朋友，全對通過！", '["design","deliver"]',
            "由唔熟到全對，好有恆心！", "勁！你係乘法達人",
            "achieved", 0.9, "rub-internal-001", _ago_iso(days=20), None,
        ),
        (
            "pf-manual-1002", "maths-fractions-01", "分數披薩工程",
            "用披薩切件學分數，完成三個級別任務。",
            "砌出完整分數披薩，解釋得好清楚。", '["deliver","communicate"]',
            "今次解說更有條理！", "好叻！分數大師出動",
            "exemplary", 0.95, "rub-internal-002", _ago_iso(days=5), None,
        ),
    ]
    for (item_id, topic, title, desc, evidence, comps, growth, kid_label,
         internal, conf, rub, achieved_at, linked) in manual_items:
        cur.execute(
            "INSERT INTO portfolio_items (item_id,student_id,topic_id,subject,"
            "title,description,evidence_excerpt,competencies_4d,growth_note,"
            "kid_label,internal_label,confidence,rubric_id,achieved_at,"
            "linked_project_id) VALUES (?,?,?,'maths',?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, SID_A, topic, title, desc, evidence, comps, growth,
             kid_label, internal, conf, rub, achieved_at, linked),
        )
    # One achieved log for the same-source parity test (SID_D empty -> 1 item).
    cur.execute(
        "INSERT INTO assessment_logs (student_id,session_id,topic_id,mode,"
        "lang_code,internal_label,confidence,rubric_id,evidence_text,agent_used,"
        "cost_tokens,created_at) VALUES (?,?,'maths-multiplication-02','DIRECT',"
        "'zh-hk','achieved',0.9,'rub-internal-003','分數拆解全對',0,0,?)",
        (SID_D, "ses-pf-parity", _ago_iso(days=1)),
    )
    conn.commit()
    conn.close()
    return {"db_path": db_path}


# ---------------------------------------------------------------------------
# Kid surface (parent session acting for the unlocked child)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_kid_surface_own_child_200_shape(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_A[:8]},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["empty"] is False
    items = body["items"]
    assert [it["item_id"] for it in items] == ["pf-manual-1002", "pf-manual-1001"]
    first = items[0]
    # shared item view fields present
    for key in ("item_id", "topic_id", "subject", "title", "description",
                "evidence_excerpt", "competencies_4d", "growth_note",
                "kid_label", "achieved_at", "linked_project_id"):
        assert key in first, f"missing item view key {key}"
    assert first["competencies_4d"] == ["deliver", "communicate"]
    # kid surface: no student id, no share_card payload (R2), no envelope leak
    text = json.dumps(body, ensure_ascii=False)
    assert "share_card" not in body and "share_cards" not in body
    assert SID_A not in text and SID_A[:8] not in text
    assert "display_name" not in body


@pytest.mark.asyncio
async def test_kid_surface_empty_portfolio_200(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_A2},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200
    body = await resp.json()
    assert body == {"items": [], "empty": True}


@pytest.mark.asyncio
async def test_kid_surface_full_id_own_child_200(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_A},
        headers=_cookie_header(P1),
    )
    assert resp.status == 200
    assert (await resp.json())["empty"] is False


@pytest.mark.asyncio
async def test_kid_surface_cross_child_403(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_D[:8]},
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_kid_surface_unknown_mask_403(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": "zzzz9999"},
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_kid_surface_ambiguous_mask_400(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": "bbbb1111"},
        headers=_cookie_header(P1),
    )
    assert resp.status == 400


@pytest.mark.asyncio
async def test_kid_surface_missing_param_400(world, client):
    resp = await client.get("/api/student/portfolio", headers=_cookie_header(P1))
    assert resp.status == 400


@pytest.mark.asyncio
async def test_kid_surface_teacher_403(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_A[:8]},
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_kid_surface_unauth_401(world, client):
    resp = await client.get(
        "/api/student/portfolio", params={"student": SID_A[:8]}, headers=HEADERS
    )
    assert resp.status == 401


# ---------------------------------------------------------------------------
# Parent surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_surface_own_child_200_shape(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}", headers=_cookie_header(P1)
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["empty"] is False
    student = body["student"]
    assert student["student_id"] == SID_A[:8]      # masked (W3-B convention)
    assert student["display_name"] == "阿明"         # B24: first_name only
    assert student["media_consent"] == "agreed"
    items = body["items"]
    cards = body["share_cards"]
    assert [it["item_id"] for it in items] == ["pf-manual-1002", "pf-manual-1001"]
    assert [c["item_id"] for c in cards] == [it["item_id"] for it in items]
    text = json.dumps(body, ensure_ascii=False)
    assert SID_A not in text  # full id never leaves the server
    assert "internal_label" not in body and "confidence" not in body
    assert "rubric_id" not in body


@pytest.mark.asyncio
async def test_parent_surface_whitelist_exact_and_negative_scan(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A[:8]}", headers=_cookie_header(P1)
    )
    assert resp.status == 200
    body = await resp.json()
    for card in body["share_cards"]:
        assert set(card) == SHARE_CARD_WHITELIST
        assert card["display_name"] == "阿明"          # B24
        assert card["brand"] == "Dreamer AI"       # frozen brand field
        assert isinstance(card["competencies_4d"], list)
    # P-series red line: grading keys/values never appear. (The plain words
    # achieved/exemplary are NOT scanned: the sanctioned field name
    # ``achieved_at`` legitimately contains "achieved" — key-level asserts
    # below plus the seeded rubric ids cover the red line.)
    text = json.dumps(body, ensure_ascii=False)
    for key in ("internal_label", "confidence", "rubric_id"):
        assert key not in body, f"banned key leaked: {key}"
    for banned in ("rub-internal-001", "rub-internal-002", "0.9", "0.95"):
        assert banned not in text, f"banned token leaked: {banned}"
    # positive check: the sanctioned timestamp field is present and rendered
    for it in body["items"]:
        assert "achieved_at" in it


@pytest.mark.asyncio
async def test_parent_surface_empty_200(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A2}", headers=_cookie_header(P1)
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["empty"] is True
    assert body["items"] == [] and body["share_cards"] == []


@pytest.mark.asyncio
async def test_parent_surface_cross_child_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_D}", headers=_cookie_header(P1)
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_parent_surface_teacher_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}", headers=_cookie_header(T1)
    )
    assert resp.status == 403


# ---------------------------------------------------------------------------
# Single share_card endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_card_single_200_whitelist(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A[:8]}/share_card/pf-manual-1001",
        headers=_cookie_header(P1),
    )
    assert resp.status == 200
    card = await resp.json()
    assert set(card) == SHARE_CARD_WHITELIST
    assert card["item_id"] == "pf-manual-1001"
    assert card["display_name"] == "阿明"


@pytest.mark.asyncio
async def test_share_card_unknown_item_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}/share_card/pf-does-not-exist",
        headers=_cookie_header(P1),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_share_card_cross_child_403(world, client):
    # Item belongs to SID_A; SID_D's parent must not read it.
    resp = await client.get(
        f"/api/parent/portfolio/{SID_D}/share_card/pf-manual-1001",
        headers=_cookie_header(P2),
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_share_card_teacher_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}/share_card/pf-manual-1001",
        headers=_cookie_header(T1),
    )
    assert resp.status == 403


# ---------------------------------------------------------------------------
# R3 same-source parity — API card == PortfolioAgent._build_share_card
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_card_same_source_parity_with_agent(world, client):
    from agents.portfolio_agent import PortfolioAgent

    agent = PortfolioAgent(db_path=world["db_path"])
    generated = agent.generate_portfolio(
        SID_D, lang_code="zh-hk", age_band="P4-P6", mode="CONTEXTUAL",
        display_name="家豪",
    )
    assert generated["portfolio"]["items"], "parity seed item should exist"
    agent_card = generated["portfolio"]["share_cards"][0]

    resp = await client.get(
        f"/api/parent/portfolio/{SID_D}", headers=_cookie_header(P2)
    )
    assert resp.status == 200
    body = await resp.json()
    api_card = body["share_cards"][0]
    # generated_at is wall-clock on each call — compare everything else.
    api_card.pop("generated_at")
    agent_card.pop("generated_at")
    assert api_card == agent_card
    assert set(api_card) == SHARE_CARD_WHITELIST - {"generated_at"}


# ---------------------------------------------------------------------------
# W4 PR-C — parent portfolio PDF endpoint (/api/parent/portfolio/{id}/pdf)
# ---------------------------------------------------------------------------


def _pdf_text(resp_body: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(resp_body))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


@pytest.mark.asyncio
async def test_portfolio_pdf_own_child_200_pdpo_clean(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}/pdf", headers=_cookie_header(P1)
    )
    assert resp.status == 200
    assert resp.headers["Content-Type"].startswith("application/pdf")
    assert "portfolio-" in resp.headers.get("Content-Disposition", "")
    body = await resp.read()
    text = _pdf_text(body)
    # §3 sections + CJK round-trip
    for probe in ("作品集", "阿明", "乘法小挑戰", "分數披薩工程", "成長點滴", "成長：", "Dreamer AI"):
        assert probe in text, f"PDF missing {probe}"
    # §6.3 PDPO scan — seeded internal identifiers must never appear
    for banned in (
        SID_A, SID_A[:8], "rub-internal-001", "rub-internal-002",
        "confidence", "exemplary", "achieved",
    ):
        assert banned.lower() not in text.lower(), f"PDF leaked {banned}"


@pytest.mark.asyncio
async def test_portfolio_pdf_empty_portfolio_200_single_page(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A2}/pdf", headers=_cookie_header(P1)
    )
    assert resp.status == 200
    body = await resp.read()
    from io import BytesIO

    from pypdf import PdfReader

    pages = PdfReader(BytesIO(body)).pages
    assert len(pages) == 1
    text = pages[0].extract_text() or ""
    assert "繼續探索新項目" in text
    assert "作品亮點" not in text


@pytest.mark.asyncio
async def test_portfolio_pdf_cross_child_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}/pdf", headers=_cookie_header(P2)
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_portfolio_pdf_teacher_403(world, client):
    resp = await client.get(
        f"/api/parent/portfolio/{SID_A}/pdf", headers=_cookie_header(T1)
    )
    assert resp.status == 403


@pytest.mark.asyncio
async def test_portfolio_pdf_unauth_401(world, client):
    resp = await client.get(f"/api/parent/portfolio/{SID_A}/pdf")
    assert resp.status == 401
