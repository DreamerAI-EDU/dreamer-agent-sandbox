// PR-5 A2 — generate a draft (POST /api/teacher/reports/generate).
//
// one-pending gate: the backend answers 409 + {report_id, draft_url} when the
// student already has a pending_review draft. The form surfaces that as a
// clickable entry to the existing draft instead of an opaque error (§4.4).
// lang_code is NOT sent: the server reads it from the student row.

import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../../lib/api';
import { WEEK_MAX, WEEK_MIN } from '../../lib/reportTypes';
import { TeacherConsoleFrame } from './TeacherConsoleFrame';
import { mask, useTeacherRoster } from '../../hooks/useTeacherRoster';

interface Conflict {
  message: string;
  reportId: string;
  draftUrl: string;
}

const WEEKS = Array.from({ length: WEEK_MAX - WEEK_MIN + 1 }, (_, i) => WEEK_MIN + i);

export function TeacherGeneratePage() {
  const roster = useTeacherRoster();
  const [classId, setClassId] = useState('');
  const [studentId, setStudentId] = useState('');
  const [weekFrom, setWeekFrom] = useState(WEEK_MIN);
  const [weekTo, setWeekTo] = useState(WEEK_MAX);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [created, setCreated] = useState<{ reportId: string } | null>(null);

  const classStudents = useMemo(
    () => roster.students.filter((s) => s.class_id === classId),
    [roster.students, classId],
  );
  const selected = classStudents.find((s) => s.student_id === studentId) ?? null;

  const generate = async () => {
    setError('');
    setConflict(null);
    setCreated(null);
    if (!classId || !studentId) {
      setError('請先揀班別同學生');
      return;
    }
    if (weekFrom > weekTo) {
      setError('起始週不可大於結束週');
      return;
    }
    setBusy(true);
    try {
      const resp = await api.teacherReportGenerate({
        class_id: classId,
        student_id: studentId,
        week_from: weekFrom,
        week_to: weekTo,
      });
      setCreated({ reportId: resp.report_id });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        const body = (err.body ?? {}) as { report_id?: unknown; draft_url?: unknown };
        const reportId = typeof body.report_id === 'string' ? body.report_id : '';
        const draftUrl =
          typeof body.draft_url === 'string' && body.draft_url
            ? body.draft_url
            : reportId
              ? `/teacher/reports/${reportId}`
              : '';
        setConflict({
          message: err.message,
          reportId,
          draftUrl,
        });
      } else {
        setError(err instanceof ApiError ? err.message : '生成失敗');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <TeacherConsoleFrame
      title="生成報告草稿"
      subtitle="揀學生＋週區間，草稿會進入 pending_review 等老師審閱"
    >
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="text-xs font-bold text-black/50">
            班別
            <select
              value={classId}
              onChange={(e) => {
                setClassId(e.target.value);
                setStudentId('');
                setConflict(null);
                setCreated(null);
              }}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              data-testid="generate-class"
            >
              <option value="">選擇班別</option>
              {roster.classes.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs font-bold text-black/50">
            學生
            <select
              value={studentId}
              onChange={(e) => {
                setStudentId(e.target.value);
                setConflict(null);
                setCreated(null);
              }}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              disabled={!classId}
              data-testid="generate-student"
            >
              <option value="">選擇學生</option>
              {classStudents.map((s) => (
                <option key={s.student_id} value={s.student_id}>
                  {s.display_name}（{mask(s.student_id)}）
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs font-bold text-black/50">
            由第幾週
            <select
              value={weekFrom}
              onChange={(e) => setWeekFrom(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              data-testid="generate-week-from"
            >
              {WEEKS.map((w) => (
                <option key={w} value={w}>
                  第 {w} 週
                </option>
              ))}
            </select>
          </label>

          <label className="text-xs font-bold text-black/50">
            至第幾週
            <select
              value={weekTo}
              onChange={(e) => setWeekTo(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              data-testid="generate-week-to"
            >
              {WEEKS.map((w) => (
                <option key={w} value={w}>
                  第 {w} 週
                </option>
              ))}
            </select>
          </label>
        </div>

        {roster.loading && <p className="mt-4 text-sm text-black/40">載入班別…</p>}
        {roster.error && <p className="mt-4 text-sm text-red-600">{roster.error}</p>}

        {selected && (
          <p className="mt-3 text-xs text-black/40">
            報告語言（由學生紀錄決定）{selected.lang_code} · 階段{' '}
            {selected.age_band ?? '—'}
          </p>
        )}

        <div className="mt-4">
          <button
            type="button"
            onClick={generate}
            disabled={busy || !studentId}
            className="rounded-full bg-[#00023D] px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
            data-testid="generate-submit"
          >
            {busy ? '生成中…' : '生成草稿'}
          </button>
        </div>

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        {conflict && (
          <div
            className="mt-4 rounded-xl border border-amber-300 bg-amber-50 p-4"
            data-testid="generate-conflict"
          >
            <p className="text-sm font-bold text-amber-800">{conflict.message}</p>
            <p className="mt-1 text-xs text-amber-700">
              呢位學生已有一份待審草稿，請先處理咗佢再生成新版本。
            </p>
            {conflict.draftUrl && (
              <Link
                to={conflict.draftUrl}
                className="mt-2 inline-block rounded-full bg-[#00023D] px-4 py-1.5 text-xs font-bold text-white"
                data-testid="generate-conflict-link"
              >
                前往現有草稿
              </Link>
            )}
          </div>
        )}

        {created && (
          <div
            className="mt-4 rounded-xl border border-emerald-300 bg-emerald-50 p-4"
            data-testid="generate-created"
          >
            <p className="text-sm font-bold text-emerald-800">草稿已生成（pending_review）</p>
            <Link
              to={`/teacher/reports/${created.reportId}`}
              className="mt-2 inline-block rounded-full bg-[#00023D] px-4 py-1.5 text-xs font-bold text-white"
            >
              開始審閱
            </Link>
          </div>
        )}
      </div>
    </TeacherConsoleFrame>
  );
}
