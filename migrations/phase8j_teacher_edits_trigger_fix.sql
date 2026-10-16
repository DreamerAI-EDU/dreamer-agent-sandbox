-- ==========================================================================
-- phase8j — PR-4 teacher_edits 追加闸 LIKE→substr 修复（PR-3 发现 B，施工令 2026-10-16）
-- 纯增量、幂等（DROP TRIGGER IF EXISTS + CREATE），无 ALTER、无数据搬迁。
-- 背景：phase8i ③ 的闸用 LIKE 做前缀对碰，SQL 通配符 %／_ 会被当成通配符 ——
--       旧值里含 % 或 _ 时，同长度改写（把 %/_ 处换成别的字符）仍会「像前缀」
--       而放行，字段级 diff 审计链可被静默抹除。本档改为 substr 逐字对碰。
-- 约束：phase8i 已 commit，不准改写；本档 DROP + 重建同名触发器覆盖之。
-- 镜像：auth/db.py 的 _PR4_TEACHER_EDITS_TRIGGER_FIX_DDL，逐字对应本档。
-- 应用：python -c "from auth import db; db.apply_phase8j_teacher_edits_trigger_fix()"
-- ==========================================================================

-- ③（修复版）teacher_edits 只增不减、不可重写（§4.2）
--    语义与 phase8i 一致：数组长度不得缩短，且新值必须以旧值去掉尾部 ']' 后
--    的字符串为前缀。区别只在「前缀对碰」由 LIKE 通配符改为 substr 逐字比较，
--    含 %／_ 的旧值不再能被同长度改写绕过。
DROP TRIGGER IF EXISTS parent_reports_teacher_edits_append_only;
CREATE TRIGGER parent_reports_teacher_edits_append_only
BEFORE UPDATE OF teacher_edits ON parent_reports
FOR EACH ROW
WHEN json_valid(OLD.teacher_edits) AND json_valid(NEW.teacher_edits)
     AND (
          json_array_length(NEW.teacher_edits) < json_array_length(OLD.teacher_edits)
          OR substr(NEW.teacher_edits, 1, length(OLD.teacher_edits) - 1)
             != substr(OLD.teacher_edits, 1, length(OLD.teacher_edits) - 1)
     )
BEGIN
    SELECT RAISE(ABORT, 'parent_reports.teacher_edits is append-only (no rewrite, no shrink)');
END;
