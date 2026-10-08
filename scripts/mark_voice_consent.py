#!/usr/bin/env python
"""c1-13b — operator marking tool for the voice-consent trial rows.

Since 2026-10-08 the voice_consent copy is approved and the document is a
normal, parent-visible consent (ticked on the signup consent page, withdrawn
on its own row) — so this script now RETIRES ITSELF: the is_trial_only guard
in main() refuses every run. It stays in the repo as the audit trail of the
trial path: while the copy was still a draft, only this script could write a
row, and only for a test account whose guardian consent was already on file
offline (signed paper form / recorded call with the school).

There is no shortcut around this: the script only records a row that already
has an offline basis. It refuses to guess, refuses to touch non-trial
accounts, and never writes anything to the audit log beyond a masked id.

NOTE (2026-10-08): the doc has landed, so every run below now exits 3 at the
trial guard — the commands are kept for history only.

Usage (from the repo root, venv active):

    # see who would be marked, write nothing
    python scripts/mark_voice_consent.py --student 3f9a1c2d --dry-run

    # record the trial row (guardian consent on file)
    python scripts/mark_voice_consent.py --student 3f9a1c2d --by "paper form 2026-10-06" --ack-trial

    # withdraw (e.g. the trial ends, or a guardian says stop)
    python scripts/mark_voice_consent.py --student 3f9a1c2d --withdraw --ack-trial

Exit codes: 0 ok, 2 usage / lookup problem, 3 refused by a safety check.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from auth import consent, db  # noqa: E402  (path bootstrap above)

DOC_TYPE = "voice_consent"
MASK = "operator-script:scripts/mark_voice_consent.py"


def _fail(message: str, code: int = 2) -> "None":
    print(f"REFUSED: {message}", file=sys.stderr)
    sys.exit(code)


def _resolve_student(token: str) -> dict:
    token = token.strip()
    if not token:
        _fail("--student is empty")
    db.ensure_schema()
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT id, parent_id, first_name, age_band FROM students "
            "WHERE id = ? OR id LIKE ? ORDER BY id",
            (token, f"{token}%"),
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        _fail(f"no student matches {token!r}")
    if len(rows) > 1:
        # Never guess which child: print the candidates (masked) and stop.
        print("multiple students match; re-run with a longer prefix:", file=sys.stderr)
        for row in rows:
            print(
                f"  {row['id'][:8]}…  band={row['age_band']}  "
                f"parent={'set' if row['parent_id'] else 'missing'}",
                file=sys.stderr,
            )
        sys.exit(2)
    return dict(rows[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--student", required=True, help="student id or prefix")
    parser.add_argument("--withdraw", action="store_true", help="write withdrawn")
    parser.add_argument("--by", default="", help="offline consent basis (kept in the audit line)")
    parser.add_argument("--dry-run", action="store_true", help="show state, write nothing")
    parser.add_argument(
        "--ack-trial",
        action="store_true",
        help="confirm this is a trial test account with guardian consent on file",
    )
    args = parser.parse_args()

    cfg = consent.get_doc_config(DOC_TYPE)
    if cfg is None:
        _fail(f"{DOC_TYPE} is not in config/consent_docs.yaml", 3)
    if not consent.is_trial_only(cfg):
        # The draft has been promoted to a real document: parents sign it
        # themselves now, and this tool must not fabricate rows for them.
        _fail(
            f"{DOC_TYPE} is no longer trial_only — parents sign it in the app; "
            "this script is retired for that doc",
            3,
        )

    student = _resolve_student(args.student)
    sid = student["id"]
    parent_id = student["parent_id"]
    masked = f"{sid[:8]}…"
    version = cfg["current_version"]

    before = bool(parent_id) and consent.student_has_current_agreement(
        parent_id, DOC_TYPE, sid
    )
    action = "withdrawn" if args.withdraw else "agreed"
    print(f"student {masked}  band={student['age_band']}")
    print(f"  consent now: {'agreed' if before else 'absent'}")
    print(f"  would write: doc={DOC_TYPE} version={version} action={action}")

    if args.dry_run:
        print("dry-run: nothing written")
        return 0

    if not args.ack_trial:
        _fail(
            "missing --ack-trial: this row must rest on guardian consent already "
            "on file (signed form / recorded call). Nothing was written.",
            3,
        )
    if not parent_id:
        _fail(f"student {masked} has no parent_id — no guardian to consent", 3)
    if action == "withdrawn" and not before:
        _fail(f"nothing to withdraw for {masked} (no current agreed row)", 3)
    if action == "agreed" and not args.by.strip():
        _fail("--by is required when marking agreed (name the offline basis)", 3)

    consent.insert_consent_row(
        user_id=parent_id,
        doc_type=DOC_TYPE,
        doc_version=version,
        action=action,
        ip="operator-script",
        user_agent=MASK,
        student_id=sid,
    )
    consent.write_audit_log(
        {
            "event": f"voice_consent_{action}",
            "student": masked,
            "doc_version": version,
            "by": args.by.strip() or "n/a",
            "operator": os.environ.get("USERNAME") or os.environ.get("USER") or "unknown",
        }
    )
    after = consent.student_has_current_agreement(parent_id, DOC_TYPE, sid)
    print(f"written. consent now: {'agreed' if after else 'absent'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
