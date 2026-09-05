"""W2 PR#2 — consent gate: document registry, consent log DAO, legal pages.

Scope (per W2-PR2 brief):
  - config/consent_docs.yaml is the single source of truth for document
    versions (SoT). Nothing may hardcode a version string in two places.
  - /legal/* embedded pages render the boss-approved copy verbatim; the
    header version is injected from the YAML at request time.
  - consent_log is append-only by design: sign and withdraw both INSERT a
    new row; there is deliberately no code path that mutates or removes
    existing consent rows (test 12 scans this module for such paths).
  - media_consent withdraw writes an audit-log WARNING carrying the
    media_takedown_pending flag for the human 24h takedown flow.
  - privacy_policy cannot be withdrawn via API (it is the precondition of
    using the service); the endpoint rejects with an info@ pointer.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger("dreamer.auth.consent")

_PKG_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_DIR.parent
DOCS_PATH = os.environ.get(
    "DREAMER_CONSENT_DOCS_PATH",
    str(_REPO_ROOT / "config" / "consent_docs.yaml"),
)
LEGAL_DIR = _PKG_DIR / "legal"
AUDIT_LOG_PATH = os.environ.get(
    "DREAMER_AUDIT_LOG_PATH",
    str(_REPO_ROOT / "audit_log.jsonl"),
)

# Whitelist of doc types registered in config/consent_docs.yaml.
DOC_TYPES = ("privacy_policy", "media_consent")

# Legal page -> doc_type mapping for the /legal/* embedded pages.
LEGAL_ROUTES = {
    "privacy-policy": "privacy_policy",
    "media-consent": "media_consent",
}

_ERR_INVALID = {"error": "請求無效"}


def _now_iso() -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Document registry (SoT)
# ---------------------------------------------------------------------------

def load_consent_docs() -> dict[str, Any]:
    """Load config/consent_docs.yaml (read on every call, never cached).

    Caching is deliberately avoided so a version bump in the YAML takes
    effect immediately — the consent gate and embedded pages must always
    reflect the current registry (test 9 relies on this).
    """
    with open(DOCS_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    documents = data["documents"]
    unknown = set(documents) - set(DOC_TYPES)
    if unknown:
        raise ValueError(f"unknown doc_type(s) in consent registry: {sorted(unknown)}")
    return data


def get_doc_config(doc_type: str) -> Optional[dict[str, Any]]:
    docs = load_consent_docs()
    return docs["documents"].get(doc_type)


def render_legal_page(route_key: str) -> Optional[str]:
    """Render an embedded legal page with the YAML version injected.

    route_key is the URL slug (e.g. "privacy-policy"); returns None when the
    slug is unknown. The body copy lives verbatim in auth/legal/*.html; the
    only dynamic part is {{VERSION}}, sourced from consent_docs.yaml so the
    checkbox label and the page header share one version truth.
    """
    doc_type = LEGAL_ROUTES.get(route_key)
    if doc_type is None:
        return None
    version = get_doc_config(doc_type)["current_version"]
    template = (LEGAL_DIR / f"{doc_type}.html").read_text(encoding="utf-8")
    return template.replace("{{VERSION}}", version)


# ---------------------------------------------------------------------------
# Consent log DAO (append-only)
# ---------------------------------------------------------------------------

def insert_consent_row(
    *,
    user_id: str,
    doc_type: str,
    doc_version: str,
    action: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
    student_id: Optional[str] = None,
) -> str:
    """Append a consent_log row. Returns the new row id.

    Every sign / withdraw is a fresh row (action=agreed / action=withdrawn).
    Historical rows are never touched — the latest row per (user, doc) is
    the current status.
    """
    from . import db

    row_id = str(uuid.uuid4())
    db.ensure_schema()
    conn = db.connect()
    try:
        conn.execute(
            """INSERT INTO consent_log
               (id, user_id, student_id, doc_type, doc_version, action,
                ip, user_agent, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row_id,
                user_id,
                student_id or None,
                doc_type,
                doc_version,
                action,
                ip or None,
                user_agent or None,
                _now_iso(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return row_id


def get_latest_consent_rows(user_id: str) -> dict[str, dict[str, Any]]:
    """Latest consent_log row per doc_type for a user (empty dict if none)."""
    from . import db

    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT doc_type, doc_version, action, created_at
               FROM consent_log
               WHERE user_id = ?
               ORDER BY created_at DESC, rowid DESC""",
            (user_id,),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        doc_type = row["doc_type"]
        if doc_type not in latest:
            latest[doc_type] = {
                "doc_type": doc_type,
                "doc_version": row["doc_version"],
                "action": row["action"],
                "created_at": row["created_at"],
            }
    return latest


def has_current_agreement(user_id: str, doc_type: str) -> bool:
    """True when the user holds an agreed row on the current version."""
    doc = get_doc_config(doc_type)
    if doc is None:
        return False
    current_version = doc["current_version"]
    latest = get_latest_consent_rows(user_id).get(doc_type)
    return bool(
        latest
        and latest["action"] == "agreed"
        and latest["doc_version"] == current_version
    )


def has_withdrawable_agreement(
    user_id: str,
    doc_type: str,
    student_id: Optional[str] = None,
) -> bool:
    """P3-2 prior-agree gate: may the user withdraw `doc_type` today?

    True only when a current-version `agreed` row exists that covers the
    withdraw scope. With a student_id the agreement must belong to that
    student (account-level NULL rows also cover); without one the latest
    row for the doc decides — the same scope semantics as the sign path,
    so a fresh user, a version-stale signer and a second withdraw (whose
    latest row is already `withdrawn`) are all rejected with the uniform
    "未有可撤回嘅同意紀錄" 400 instead of writing a new row.
    """
    doc = get_doc_config(doc_type)
    if doc is None:
        return False
    current_version = doc["current_version"]

    from . import db

    db.ensure_schema()
    conn = db.connect()
    try:
        if student_id:
            cur = conn.execute(
                """SELECT doc_version, action FROM consent_log
                   WHERE user_id = ? AND doc_type = ?
                     AND (student_id = ? OR student_id IS NULL)
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (user_id, doc_type, student_id),
            )
        else:
            cur = conn.execute(
                """SELECT doc_version, action FROM consent_log
                   WHERE user_id = ? AND doc_type = ?
                   ORDER BY created_at DESC, rowid DESC LIMIT 1""",
                (user_id, doc_type),
            )
        row = cur.fetchone()
    finally:
        conn.close()
    return bool(
        row
        and row["action"] == "agreed"
        and row["doc_version"] == current_version
    )


def student_media_consent_withdrawn(
    user_id: str,
    student_id: str,
) -> bool:
    """True when the student's latest media_consent row is withdrawn.

    Scope matches sign/withdraw: student-bound rows plus account-level
    NULL rows both cover the student (latest row decides, exactly the
    has_withdrawable_agreement rule). A withdrawn row means the parent
    revoked media consent for this child; the W3-A WS chat handshake
    refuses to open a new session for such a student. No media rows at
    all (never signed) is NOT a withdrawal — handshake proceeds.
    """
    from . import db

    db.ensure_schema()
    conn = db.connect()
    try:
        cur = conn.execute(
            """SELECT action FROM consent_log
               WHERE user_id = ? AND doc_type = ?
                 AND (student_id = ? OR student_id IS NULL)
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (user_id, "media_consent", student_id),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    return bool(row and row["action"] == "withdrawn")


def required_consent_gaps(user_id: str) -> list[str]:
    """Doc types that are required:true and lack a current-version agreement.

    Used by the login gate: when non-empty, the login response carries
    consent_required=true plus the missing list so the frontend can show the
    re-sign page.
    """
    docs = load_consent_docs()
    gaps = []
    for doc_type, cfg in docs["documents"].items():
        if cfg.get("required") and not has_current_agreement(user_id, doc_type):
            gaps.append(doc_type)
    return gaps


def status_for_user(user_id: str) -> dict[str, dict[str, Any]]:
    """Per-document status for /api/consent/status."""
    docs = load_consent_docs()
    latest = get_latest_consent_rows(user_id)
    out: dict[str, dict[str, Any]] = {}
    for doc_type, cfg in docs["documents"].items():
        entry = latest.get(doc_type)
        out[doc_type] = {
            "doc_type": doc_type,
            "current_version": cfg["current_version"],
            "required": bool(cfg.get("required")),
            "title_zh": cfg.get("title_zh", ""),
            "title_en": cfg.get("title_en", ""),
            "status": (
                entry["action"] if entry else "unsigned"
            ),
            "doc_version": entry["doc_version"] if entry else None,
        }
    return out


# ---------------------------------------------------------------------------
# Audit log (media takedown downstream marker)
# ---------------------------------------------------------------------------

def write_audit_log(record: dict[str, Any]) -> None:
    """Append one JSON line to the audit log (best-effort, never raises).

    The media_consent withdraw path writes a WARNING record carrying
    media_takedown_pending=true plus student_id and timestamp so the human
    operator can action the 24h takedown promise on the five channels.
    """
    path = Path(AUDIT_LOG_PATH)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        logger.warning("audit log append failed (path=%s)", AUDIT_LOG_PATH)


def record_media_takedown_pending(
    *,
    user_id: str,
    student_id: Optional[str] = None,
) -> None:
    """Marker for the human 24h takedown flow (media_consent withdraw)."""
    write_audit_log(
        {
            "timestamp": _now_iso(),
            "level": "WARNING",
            "event": "media_takedown_pending",
            "doc_type": "media_consent",
            "user_id": user_id,
            "student_id": student_id or None,
            "message": "media consent withdrawn; human takedown required within 24h",
        }
    )
