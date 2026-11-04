"""PR-5 local trilingual harness seeder.

Brings up a throw-away SQLite database that lets the boss walk the PR-5
screens in all three languages by eye (§8.3 「CI ＋ 本地人工过三语」).

What it creates
---------------
* 1 teacher account + 1 parent account (known passwords, printed at the end)
* 1 class (P4-P6) owned by that teacher
* 1 student, confirmed on that class roster, owned by that parent
* three weeks of teacher scores (4 dimensions x 3 weeks, 0-3 + one evidence line)
* seven learning sessions spread over 21 days, plus the obs_events (cost) and
  progress_snapshots rows the parent-report agent aggregates. Without them
  ``ParentReportAgent`` sees an empty student, keeps ``variant=first_steps``
  (FIRST_STEPS_MIN_SESSIONS=5 / FIRST_STEPS_MIN_DAYS=14) and every report body
  is the welcome-only template.
* three APPROVED weekly parent reports for that student, one per language:
      week 1 -> en        week 2 -> zh-hk        week 3 -> zh-cn

Each report is drafted through the same code path the API uses
(``ParentReportAgent.generate_report`` -> ``_strip_internal`` ->
``attach_dimension_descriptors`` -> ``create_pending_report`` ->
``decide_report(approve)``), so the harness shows what production produces.
Distinct week windows are deliberate: approving a second report for the SAME
window supersedes the first (design book §4.1) and the parent console would
then show only one language.

Nothing here touches the production database: ``DREAMER_DB_PATH`` is pointed at
``--db`` before any auth module is imported. An existing harness DB is renamed
aside (never deleted) unless ``--reset`` is passed.

Usage::

    .venv\Scripts\python.exe scripts/pr5_seed_local.py
    .venv\Scripts\python.exe scripts/pr5_seed_local.py --db .pr5_harness/pr5_harness.db

Incremental modes (against an existing harness DB, never rebuilding it)::

    # learning activity only (sessions / obs_events / progress_snapshots)
    .venv\Scripts\python.exe scripts/pr5_seed_local.py --learning-only

    # re-draft + approve the three per-language reports (supersedes by window)
    .venv\Scripts\python.exe scripts/pr5_seed_local.py --reissue-reports

Output: a JSON summary on stdout (also written to <out>/seed_summary.json).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

DEFAULT_DB = os.path.join(REPO_ROOT, ".pr5_harness", "pr5_harness.db")
DEFAULT_OUT = os.path.join(REPO_ROOT, ".pr5_harness", "reports")

TEACHER_ID = "user-pr5-teacher"
PARENT_ID = "user-pr5-parent"
CLASS_ID = "class-pr5-demo"
STUDENT_ID = "stud-pr5-demo0001"

TEACHER_EMAIL = "teacher@pr5.local"
PARENT_EMAIL = "parent@pr5.local"
HARNESS_PASSWORD = "Pr5Harness!2026"   # throw-away local-only account password
STUDENT_PIN = "1234"                   # parent-dashboard PIN for the demo child

AGE_BAND = "P4-P6"
STUDENT_LANG = "zh-hk"
STUDENT_NAME = "陳小明"

#: week -> language for the three approved reports (see module docstring).
REPORT_PLAN = ((1, "en"), (2, "zh-hk"), (3, "zh-cn"))

SKILLS = ("DREAM", "DISCOVER", "DESIGN", "DELIVER")

#: Scores per week (0-3) + one evidence line each (<=200 chars, C3).
SCORE_PLAN: dict[int, dict[str, tuple[int, str]]] = {
    1: {
        "DREAM": (2, "第一週：能自己講出三個唔同嘅故事結局，其中一個係原創。"),
        "DISCOVER": (1, "第一週：搵資料時仍要老師提示先會查證來源。"),
        "DESIGN": (2, "第一週：草圖有清楚分鏡，落筆前會先講一次步驟。"),
        "DELIVER": (1, "第一週：小組分享時聲線偏細，需要第二次邀請先講完。"),
    },
    2: {
        "DREAM": (3, "第二週：把兩個唔相關嘅念頭駁埋，做出一個全新角色設定。"),
        "DISCOVER": (2, "第二週：主動對比兩個網站說法，指出其中一處矛盾。"),
        "DESIGN": (2, "第二週：按同學回饋改咗兩版，版本之間差異講得出理由。"),
        "DELIVER": (2, "第二週：可以完整講完一分鐘，眼神開始望住觀眾。"),
    },
    3: {
        "DREAM": (3, "第三週：連續三次提出唔同方向，並且自己淘汰其中兩個。"),
        "DISCOVER": (3, "第三週：自己設計咗三個查證步驟，仲教識旁邊同學。"),
        "DESIGN": (3, "第三週：成品同草圖一致，仲加咗一處自己想到嘅細節。"),
        "DELIVER": (2, "第三週：台上表現穩定，答問題時會先重述再回應。"),
    },
}

#: Learning activity: (days_ago, mode, duration_seconds, cost_tokens, topic_ids).
#: 8 sessions over 21 days. Two constraints at once: the whole set spans
#: >= FIRST_STEPS_MIN_DAYS (14) with >= FIRST_STEPS_MIN_SESSIONS (5) so the agent
#: leaves variant="first_steps", AND five of them sit inside the last 7 days so
#: the three weekly (period=weekly, 7-day window) reports carry real activity
#: instead of a near-empty window.
SESSION_PLAN: tuple[tuple[int, str, int, int, tuple[str, ...]], ...] = (
    (21, "DIRECT", 1500, 8200, ("computing-scratch-basics-01",)),
    (17, "CONTEXTUAL", 1800, 9400,
     ("computing-scratch-basics-01", "design-storyboard-02")),
    (13, "HYBRID", 2100, 11200, ("design-storyboard-02",)),
    (6, "DIRECT", 1650, 7600, ("computing-scratch-basics-01",)),
    (5, "CONTEXTUAL", 2400, 12800,
     ("computing-scratch-basics-01", "design-storyboard-02")),
    (3, "HYBRID", 1950, 10100, ("design-storyboard-02",)),
    (2, "DIRECT", 2050, 11600, ("computing-scratch-basics-01",)),
    (0, "HYBRID", 2200, 12200,
     ("computing-scratch-basics-01", "design-storyboard-02")),
)

#: progress_snapshots rows: (topic_id, mastery_pct, attempts, last_label, streak).
#: topic_id drives the parent-facing "subject" label (the prefix before the first
#: dash), so these read as computing / design instead of a raw id.
#: NOTE mastery_pct is a 0..1 fraction (agents/assessment_agent.py upserts the
#: rolling average on that scale; config/dreamer_progress_levels.json maps
#: achieved -> 0.75, developing -> 0.50). Seeding 68.0 here made every parent
#: surface render "6800%", so the values stay on the 0..1 scale.
TOPIC_PLAN: tuple[tuple[str, float, int, str, int], ...] = (
    ("computing-scratch-basics-01", 0.68, 7, "achieved", 3),
    ("design-storyboard-02", 0.52, 5, "developing", 2),
)

#: Prefix on every seeded session id — the tag the incremental re-run deletes by.
SEED_SESSION_PREFIX = "pr5-seed-"

AGENT_DDL = """
CREATE TABLE IF NOT EXISTS assessment_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '', mode TEXT NOT NULL DEFAULT 'DIRECT',
    lang_code TEXT NOT NULL DEFAULT 'en', internal_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0, rubric_id TEXT NOT NULL DEFAULT '',
    evidence_text TEXT NOT NULL DEFAULT '', agent_used TEXT NOT NULL DEFAULT 'assessment',
    cost_tokens INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_logs_student ON assessment_logs(student_id, created_at);
CREATE INDEX IF NOT EXISTS idx_logs_topic ON assessment_logs(topic_id, created_at);
CREATE TABLE IF NOT EXISTS progress_snapshots (
    student_id TEXT NOT NULL, topic_id TEXT NOT NULL,
    mastery_pct REAL NOT NULL DEFAULT 0.0, attempt_count INTEGER NOT NULL DEFAULT 1,
    last_label TEXT NOT NULL DEFAULT '', streak INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL, PRIMARY KEY (student_id, topic_id));
CREATE INDEX IF NOT EXISTS idx_snapshots_student ON progress_snapshots(student_id);
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    student_id TEXT NOT NULL, mode TEXT NOT NULL DEFAULT '',
    lang_code TEXT NOT NULL DEFAULT '', age_band TEXT NOT NULL DEFAULT '',
    agent_list TEXT NOT NULL DEFAULT '[]', topic_ids TEXT NOT NULL DEFAULT '[]',
    cost_summary TEXT NOT NULL DEFAULT '{}', duration_seconds INTEGER,
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS obs_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '', event_type TEXT NOT NULL,
    event_data TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now')));
"""


def _iso(**delta: int) -> str:
    return (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(**delta)
    ).isoformat().replace("+00:00", "Z")


def _fail(message: str) -> None:
    print(f"SEED FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _counts(db_path: str) -> dict[str, int]:
    """Raw row counts for the three tables the report agent aggregates."""
    conn = sqlite3.connect(db_path)
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("session_logs", "obs_events", "progress_snapshots")
        }
    finally:
        conn.close()


def _seed_learning_activity(db_path: str) -> dict[str, int]:
    """Write the demo learning activity the parent-report agent reads.

    Three things decide what a parent report says: ``session_logs`` (variant +
    session count + time spent + timeline), ``obs_events`` event_type='cost'
    (cost_summary) and ``progress_snapshots`` (per-topic mastery). Rows are
    tagged with ``SEED_SESSION_PREFIX`` and deleted before re-inserting, so the
    call is idempotent — run it twice and the counts stay put. Only the three
    tables above are touched; assessment_logs / scores / reports are left alone.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "DELETE FROM session_logs WHERE session_id LIKE ?",
            (f"{SEED_SESSION_PREFIX}%",),
        )
        conn.execute(
            "DELETE FROM obs_events WHERE session_id LIKE ?",
            (f"{SEED_SESSION_PREFIX}%",),
        )
        for index, (days_ago, mode, duration, tokens, topic_ids) in enumerate(
            SESSION_PLAN, start=1
        ):
            session_id = f"{SEED_SESSION_PREFIX}sess-{index:02d}"
            created_at = _iso(days=days_ago)
            conn.execute(
                "INSERT INTO session_logs (session_id, student_id, mode,"
                " lang_code, age_band, agent_list, topic_ids, cost_summary,"
                " duration_seconds, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    STUDENT_ID,
                    mode,
                    STUDENT_LANG,
                    AGE_BAND,
                    json.dumps(["assessment", "portfolio"], ensure_ascii=False),
                    json.dumps(list(topic_ids), ensure_ascii=False),
                    json.dumps(
                        {"status": "ok", "total_tokens": tokens}, ensure_ascii=False
                    ),
                    duration,
                    created_at,
                ),
            )
            conn.execute(
                "INSERT INTO obs_events (student_id, session_id, event_type,"
                " event_data, created_at) VALUES (?, ?, ?, ?, ?)",
                (
                    STUDENT_ID,
                    session_id,
                    "cost",
                    json.dumps(
                        {"total_tokens": tokens, "model": "pr5-harness-demo"},
                        ensure_ascii=False,
                    ),
                    created_at,
                ),
            )
        for topic_id, mastery, attempts, label, streak in TOPIC_PLAN:
            conn.execute(
                "INSERT OR REPLACE INTO progress_snapshots (student_id, topic_id,"
                " mastery_pct, attempt_count, last_label, streak, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    STUDENT_ID,
                    topic_id,
                    mastery,
                    attempts,
                    label,
                    streak,
                    _iso(days=1),
                ),
            )
        conn.commit()
        return _counts_conn(conn)
    finally:
        conn.close()


def _counts_conn(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for table in ("session_logs", "obs_events", "progress_snapshots")
    }


def _reissue_reports(db_path: str, out_dir: str) -> list[dict[str, Any]]:
    """Draft + approve one report per language, each on its own week window.

    Same code path the teacher console uses (``POST /api/teacher/reports/generate``
    -> ``create_pending_report`` -> ``decide_report(approve)``), with one
    difference: the language comes from ``REPORT_PLAN`` instead of the student
    row. The API always drafts in ``students.lang_code``, so a trilingual harness
    cannot be rebuilt through the teacher endpoint alone.

    Re-running supersedes the previously approved report of the same
    (student, class, week_from, week_to) — design book §4.1, not data loss:
    distinct weeks per language keep all three readable side by side.
    """
    from agents.parent_report_agent import ParentReportAgent  # noqa: E402
    from auth import report_descriptors as desc_mod       # noqa: E402
    from auth import report_store as store_mod            # noqa: E402
    from auth.reports import _strip_internal              # noqa: E402

    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for week, lang in REPORT_PLAN:
        envelope = ParentReportAgent(db_path=db_path).generate_report(
            student_id=STUDENT_ID,
            period="weekly",
            lang_code=lang,
            age_band=AGE_BAND,
            include_safety=True,
        )
        _strip_internal(envelope)  # parent/teacher surfaces never see P-series
        scores = store_mod.build_dimension_scores(STUDENT_ID, week, week)
        desc_mod.attach_dimension_descriptors(
            envelope, scores=scores, age_band=AGE_BAND, lang_code=lang
        )
        row = store_mod.create_pending_report(
            student_id=STUDENT_ID,
            class_id=CLASS_ID,
            lang_code=lang,
            age_band=AGE_BAND,
            week_from=week,
            week_to=week,
            scores=scores,
            payload=envelope,
            generated_by="pr5_seed_local.py",
        )
        approved = store_mod.decide_report(
            report_id=row["report_id"],
            decision="approve",
            teacher_id=TEACHER_ID,
            note=f"PR-5 harness auto-approve ({lang})",
        )
        payload_path = os.path.join(out_dir, f"report_week{week}_{lang}.json")
        with open(payload_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(approved, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        reports.append(
            {
                "report_id": approved["report_id"],
                "lang_code": lang,
                "week_from": week,
                "week_to": week,
                "version": approved["version"],
                "status": approved["status"],
                "variant": (approved.get("payload") or {}).get("meta", {}).get(
                    "variant"
                ),
                "teacher_url": f"/teacher/reports/{approved['report_id']}",
                "parent_url": f"/parent/reports/{approved['report_id']}",
                "payload_file": payload_path,
            }
        )
    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB, help="harness SQLite path")
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help="artifacts dir (report payload JSONs + seed_summary.json)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="move an existing harness DB aside (<db>.bak-<timestamp>) and rebuild",
    )
    parser.add_argument(
        "--learning-only",
        action="store_true",
        help="seed learning activity into an EXISTING harness DB (idempotent)",
    )
    parser.add_argument(
        "--reissue-reports",
        action="store_true",
        help="re-draft + approve the three per-language reports in an EXISTING DB",
    )
    args = parser.parse_args(argv)

    db_path = os.path.abspath(args.db)
    out_dir = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    if args.learning_only or args.reissue_reports:
        # Incremental path: never rebuilds, never renames — the harness DB keeps
        # its accounts, class and already-approved reports.
        if not os.path.exists(db_path):
            _fail(f"{db_path} does not exist — run the full seed first")
        if args.learning_only and args.reissue_reports:
            _fail("pass one of --learning-only / --reissue-reports, not both")
        os.environ["DREAMER_DB_PATH"] = db_path
        result: dict[str, Any] = {"db": db_path, "counts_before": _counts(db_path)}
        if args.learning_only:
            result["counts_after"] = _seed_learning_activity(db_path)
        if args.reissue_reports:
            result["reports"] = _reissue_reports(db_path, out_dir)
        result["counts_final"] = _counts(db_path)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if os.path.exists(db_path):
        if not args.reset:
            _fail(
                f"{db_path} already exists — pass --reset to rebuild the demo DB"
                " (the old file is renamed aside, never deleted)"
            )
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        for suffix in ("", "-wal", "-shm"):
            source = db_path + suffix
            if os.path.exists(source):
                os.replace(source, f"{source}.bak-{stamp}")

    os.environ["DREAMER_DB_PATH"] = db_path

    # Imports below MUST stay after DREAMER_DB_PATH is set. The report drafting
    # imports live inside _reissue_reports for the same reason — they are only
    # needed once the env var points at this harness DB.
    from auth import classes as classes_mod          # noqa: E402
    from auth import db as auth_db                   # noqa: E402
    from auth import report_store as store_mod       # noqa: E402
    from auth import scores as scores_mod            # noqa: E402
    from auth import students as students_mod        # noqa: E402
    from auth.security import hash_password          # noqa: E402

    # 1. schema: auth tables, the agent-layer tables, then the phase8 reports
    #    migration (it ALTERs assessment_logs, so the agent DDL must run first).
    auth_db.ensure_schema()
    auth_db.apply_class_meta_migration()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(AGENT_DDL)
        conn.commit()
    finally:
        conn.close()
    auth_db.apply_phase8_parent_reports_migration()

    # 2. accounts
    auth_db.create_user(
        user_id=TEACHER_ID,
        email=TEACHER_EMAIL,
        password_hash=hash_password(HARNESS_PASSWORD),
        role="teacher",
        email_verified=True,
    )
    auth_db.create_user(
        user_id=PARENT_ID,
        email=PARENT_EMAIL,
        password_hash=hash_password(HARNESS_PASSWORD),
        role="parent",
        email_verified=True,
    )

    # 3. class + student + confirmed roster
    classes_mod.create_class(
        class_id=CLASS_ID,
        teacher_id=TEACHER_ID,
        name="PR-5 三語示範班",
        join_code="PR5DEMO1",
        class_type="monthly",
        grade_band=AGE_BAND,
    )
    students_mod.create_student(
        student_id=STUDENT_ID,
        first_name=STUDENT_NAME,
        age_band=AGE_BAND,
        lang_code=STUDENT_LANG,
        pin_hash=students_mod.hash_pin(STUDENT_PIN),
        parent_id=PARENT_ID,
        teacher_id=TEACHER_ID,
    )
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO class_students (class_id, student_id, status, created_at)"
            " VALUES (?, ?, 'confirmed', ?)",
            (CLASS_ID, STUDENT_ID, _iso(days=30)),
        )
        conn.commit()
    finally:
        conn.close()

    # 4. three weeks of 4D scores
    score_rows: list[dict[str, Any]] = []
    for week, per_skill in SCORE_PLAN.items():
        for skill in SKILLS:
            value, evidence = per_skill[skill]
            result = scores_mod.upsert_teacher_score(
                student_id=STUDENT_ID,
                class_id=CLASS_ID,
                week_no=week,
                skill_code=skill,
                score=value,
                evidence=evidence,
                teacher_id=TEACHER_ID,
                age_band=AGE_BAND,
                lang_code=STUDENT_LANG,
            )
            score_rows.append(
                {
                    "week": week,
                    "skill": skill,
                    "score": value,
                    "status": result["status"],
                }
            )

    # 5. learning activity: sessions / cost events / mastery snapshots. Runs
    #    BEFORE the reports so the agent drafts real content instead of the
    #    first_steps welcome template (>=5 sessions over >=14 days).
    learning_counts = _seed_learning_activity(db_path)

    # 6. three approved reports, one language each (distinct week windows)
    student = students_mod.get_student_by_id(STUDENT_ID)
    if student is None:
        _fail("student row vanished right after creation")

    reports = _reissue_reports(db_path, out_dir)

    visible = store_mod.list_approved_for_student(STUDENT_ID)
    if len(visible) != len(REPORT_PLAN):
        _fail(
            f"expected {len(REPORT_PLAN)} approved reports visible to the parent,"
            f" got {len(visible)}"
        )

    summary = {
        "db": db_path,
        "artifacts": out_dir,
        "accounts": {
            "teacher": {"email": TEACHER_EMAIL, "password": HARNESS_PASSWORD},
            "parent": {"email": PARENT_EMAIL, "password": HARNESS_PASSWORD},
            "student_pin": STUDENT_PIN,
        },
        "ids": {
            "teacher_id": TEACHER_ID,
            "parent_id": PARENT_ID,
            "class_id": CLASS_ID,
            "student_id": STUDENT_ID,
            "age_band": AGE_BAND,
            "student_lang": STUDENT_LANG,
        },
        "scores": score_rows,
        "learning_activity": learning_counts,
        "reports": reports,
        "parent_visible_reports": len(visible),
    }
    summary_path = os.path.join(out_dir, "seed_summary.json")
    with open(summary_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nseed summary written to {summary_path}")
    print(
        "start the harness with:  powershell -ExecutionPolicy Bypass"
        " -File scripts/pr5_start_local.ps1 -Seed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
