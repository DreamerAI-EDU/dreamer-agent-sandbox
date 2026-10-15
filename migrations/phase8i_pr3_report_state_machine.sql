-- ==========================================================================
-- phase8i — PR-3 报告落库状态机硬闸（设计书 v1.1 §3.2 / §4.1，施工令 2026-10-15）
-- 纯增量、幂等（全部 IF NOT EXISTS），无 ALTER、无数据搬迁、无部署窗口。
-- 镜像：auth/db.py 的 _PR3_TEACHER_SCORE_UNIQUE_DDL（①）与
--       _PR3_PARENT_REPORTS_GUARDS_DDL（②③），两者逐字对应本档。
-- 应用：python -c "from auth import db; db.apply_phase8i_pr3_migration()"
-- ==========================================================================

-- ① TOCTOU 硬闸（PR-2 遗留，老板红线：第二次写不能靠应用程序把关）
--    同一 (student_id, week_no, skill_code) 只容许一行活着的老师评分。
--    两个并发的 PUT /api/teacher/scores 不再可能双双 INSERT —— 第二次由
--    DB 自己拒绝（唯一索引冲突），read-then-write 的竞态窗口被物理封死。
CREATE UNIQUE INDEX IF NOT EXISTS uq_assessment_teacher_score
    ON assessment_logs(student_id, week_no, skill_code)
    WHERE scored_by = 'teacher';

-- ② 报告行永不 DELETE（§3.2「只 UPDATE status／版本 supersede，永不 DELETE」）
--    状态迁移只动 status/版本，审计历史全留。
CREATE TRIGGER IF NOT EXISTS parent_reports_no_delete
BEFORE DELETE ON parent_reports
BEGIN
    SELECT RAISE(ABORT, 'parent_reports is append-only (no DELETE, design book v1.1 §3.2)');
END;

-- ③ teacher_edits 只增不减、不可重写（§4.2「每项改动 append 入 teacher_edits」）
--    新值必须以旧值为前缀（去掉尾部 ']' 后）才能通过，且数组长度不得缩短：
--    字段级 diff 审计链无法被静默抹除。
CREATE TRIGGER IF NOT EXISTS parent_reports_teacher_edits_append_only
BEFORE UPDATE OF teacher_edits ON parent_reports
FOR EACH ROW
WHEN json_valid(OLD.teacher_edits) AND json_valid(NEW.teacher_edits)
     AND (
          json_array_length(NEW.teacher_edits) < json_array_length(OLD.teacher_edits)
          OR NEW.teacher_edits NOT LIKE
             substr(OLD.teacher_edits, 1, length(OLD.teacher_edits) - 1) || '%'
     )
BEGIN
    SELECT RAISE(ABORT, 'parent_reports.teacher_edits is append-only (no rewrite, no shrink)');
END;
