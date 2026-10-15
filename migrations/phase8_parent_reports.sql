-- Dreamer AI Phase 8 — Parent Report DB Schema (家长评估报告_设计书_v1.1 §3, PR-1)
-- PR-1 (2026-10-15, boss approve/go). Landed with the auth/db.py _DDL mirror
-- and tests T-1/T-2 so ensure_schema() / the pairing test stay in sync.
--
-- §3.1 H-3: assessment_logs +6 columns. Production has 0 rows (T-0 附录 B),
--   pure ALTER TABLE ADD COLUMN → no data migration / backfill risk.
--   - skill_code: 四值 DREAM / DISCOVER / DESIGN / DELIVER（家长面 4D；内部 ATL
--     对照只存 crosswalk 文档，不落库）
--   - score_0_3: H-1 钉死 0–3；既有 confidence(0.0–1.0) 保留原义，两者不混用
--   - scored_by: auto｜teacher；双栏周次（W4/W6/W7）= 同周两行、不同 skill_code
--   - report_id: 评分被采纳进某份报告时回链；未采纳为空串
-- §3.2: parent_reports 报告主表（借 plan_proposals 样板），one-pending 部分唯一
--   索引 = 幂等硬闸：同一学生同一课程同时最多一份 pending_review。
--
-- Idempotent: ALTER/CREATE 均带 IF NOT EXISTS 语义（ALTER ADD COLUMN 幂等由
--   apply 函数先行探测列存在性兜底）— safe to re-run.
-- Apply to an existing DB (idempotent):
--   python -c "from auth.db import apply_phase8_parent_reports_migration as m; m()"
-- Fresh DBs get everything from auth/db.py::ensure_schema() (the _DDL mirror,
-- same convention as phase8c_class_curriculum.sql / phase8b_password_reset.sql).

PRAGMA journal_mode=WAL;

-- §3.1 H-3：assessment_logs 扩栏（6 栏）
ALTER TABLE assessment_logs ADD COLUMN age_band   TEXT NOT NULL DEFAULT '';
ALTER TABLE assessment_logs ADD COLUMN week_no    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE assessment_logs ADD COLUMN skill_code TEXT NOT NULL DEFAULT '';
ALTER TABLE assessment_logs ADD COLUMN score_0_3  INTEGER DEFAULT NULL
    CHECK (score_0_3 IS NULL OR (score_0_3 BETWEEN 0 AND 3));
ALTER TABLE assessment_logs ADD COLUMN scored_by  TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE assessment_logs ADD COLUMN report_id  TEXT NOT NULL DEFAULT '';

-- §3.2 报告主表 parent_reports（借 plan_proposals 样板）
CREATE TABLE IF NOT EXISTS parent_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id     TEXT NOT NULL UNIQUE,
    version       INTEGER NOT NULL DEFAULT 1,
    student_id    TEXT NOT NULL,
    class_id      TEXT NOT NULL,                 -- 课程锚点（见 §3.4）
    week_from     INTEGER NOT NULL DEFAULT 1,
    week_to       INTEGER NOT NULL DEFAULT 8,
    status        TEXT NOT NULL DEFAULT 'pending_review',
    lang_code     TEXT NOT NULL DEFAULT 'zh-hk',
    age_band      TEXT NOT NULL DEFAULT '',      -- H-2 修复后恒为真实 band
    scores        TEXT NOT NULL DEFAULT '{}',    -- {"DREAM":3,"DISCOVER":2,...}
    payload       TEXT NOT NULL DEFAULT '{}',    -- 完整报告内容（按 lang_code 单语生成）
    teacher_edits TEXT NOT NULL DEFAULT '[]',    -- 老师修改审计，append-only
    review        TEXT NOT NULL DEFAULT '{}',
    cost_summary  TEXT NOT NULL DEFAULT '{}',
    generated_by  TEXT NOT NULL DEFAULT 'auto',
    pdf_path      TEXT NOT NULL DEFAULT '',
    pdf_sha256    TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL DEFAULT '',
    updated_at    TEXT NOT NULL DEFAULT '',
    approved_at   TEXT NOT NULL DEFAULT '',
    approved_by   TEXT NOT NULL DEFAULT '',
    published_at  TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_parent_reports_student
    ON parent_reports(student_id, status, version);
CREATE INDEX IF NOT EXISTS idx_parent_reports_class
    ON parent_reports(class_id, status);

-- 幂等硬闸（借 uq_plan_proposals_one_pending 样板）：
-- 同一学生同一课程同时最多一份待审
CREATE UNIQUE INDEX IF NOT EXISTS uq_parent_reports_one_pending
    ON parent_reports(student_id, class_id) WHERE status = 'pending_review';
