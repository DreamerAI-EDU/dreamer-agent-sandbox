"""PR-5 local trilingual harness seeder.

Brings up a throw-away SQLite database that lets the boss walk the PR-5
screens in all three languages by eye (§8.3 「CI ＋ 本地人工过三语」).

What it creates
---------------
* 1 teacher account + 1 parent account (known passwords, printed at the end)
* 1 class (P4-P6) owned by that teacher
* 1 student, confirmed on that class roster, owned by that parent
* three weeks of teacher scores (4 dimensions x 3 weeks, 0-3 + one evidence line)
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
    args = parser.parse_args(argv)

    db_path = os.path.abspath(args.db)
    out_dir = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

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

    # Imports below MUST stay after DREAMER_DB_PATH is set.
    from auth import classes as classes_mod          # noqa: E402
    from auth import db as auth_db                   # noqa: E402
    from auth import report_descriptors as desc_mod  # noqa: E402
    from auth import report_store as store_mod       # noqa: E402
    from auth import scores as scores_mod            # noqa: E402
    from auth import students as students_mod        # noqa: E402
    from auth.reports import _strip_internal         # noqa: E402
    from auth.security import hash_password          # noqa: E402
    from agents.parent_report_agent import ParentReportAgent  # noqa: E402

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

    # 5. three approved reports, one language each (distinct week windows)
    student = students_mod.get_student_by_id(STUDENT_ID)
    if student is None:
        _fail("student row vanished right after creation")

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
            generated_by="auto",
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
                "teacher_url": f"/teacher/reports/{approved['report_id']}",
                "parent_url": f"/parent/reports/{approved['report_id']}",
                "payload_file": payload_path,
            }
        )

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
