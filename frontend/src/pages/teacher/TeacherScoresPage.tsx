// PR-5 A1 — weekly 4D scoring form (design book §4.2 A1, §4.4 scores).
//
// Contract (frozen, do not change): PUT /api/teacher/scores takes ONE
// (student, week, dimension) per call, score 0–3 or null (null revokes) and
// evidence_text ≤ 200 chars. The server enforces both bounds (422) and the
// student's age_band is read server-side — this form only mirrors the limits
// so the teacher sees them before the request leaves.

import { useMemo, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { DIMENSIONS } from '../../lib/parentReportCopy';
import { EVIDENCE_MAX_CHARS, SCORE_MAX, WEEK_MAX, WEEK_MIN } from '../../lib/reportTypes';
import { TeacherConsoleFrame } from './TeacherConsoleFrame';
import { mask, useTeacherRoster } from '../../hooks/useTeacherRoster';

const SCORE_OPTIONS: { value: number | null; label: string }[] = [
  { value: 3, label: '3' },
  { value: 2, label: '2' },
  { value: 1, label: '1' },
  { value: 0, label: '0' },
  { value: null, label: '—' },
];

type ScoreMap = Record<string, number | null>;
type EvidenceMap = Record<string, string>;

const WEEKS = Array.from({ length: WEEK_MAX - WEEK_MIN + 1 }, (_, i) => WEEK_MIN + i);

export function TeacherScoresPage() {
  const roster = useTeacherRoster();
  const [classId, setClassId] = useState('');
  const [studentId, setStudentId] = useState('');
  const [weekNo, setWeekNo] = useState<number>(1);
  const [scores, setScores] = useState<ScoreMap>({});
  const [evidence, setEvidence] = useState<EvidenceMap>({});
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<{ ok: string[]; fail: string[] }>({
    ok: [],
    fail: [],
  });
  const [error, setError] = useState('');

  const classStudents = useMemo(
    () => roster.students.filter((s) => s.class_id === classId),
    [roster.students, classId],
  );

  const selected = classStudents.find((s) => s.student_id === studentId) ?? null;

  const save = async () => {
    setError('');
    setResult({ ok: [], fail: [] });
    if (!classId || !studentId) {
      setError('請先揀班別同學生');
      return;
    }
    const targets = DIMENSIONS.filter((d) => scores[d.code] !== undefined);
    if (targets.length === 0) {
      setError('請至少為一個維度揀分數');
      return;
    }
    setSaving(true);
    const ok: string[] = [];
    const fail: string[] = [];
    for (const dim of targets) {
      try {
        await api.teacherPutScore({
          class_id: classId,
          student_id: studentId,
          week_no: weekNo,
          skill_code: dim.code,
          score_0_3: scores[dim.code] ?? null,
          evidence_text: evidence[dim.code] ?? '',
        });
        ok.push(dim.code);
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : '儲存失敗';
        fail.push(`${dim.code}：${msg}`);
      }
    }
    setSaving(false);
    setResult({ ok, fail });
  };

  return (
    <TeacherConsoleFrame
      title="每週評分"
      subtitle="每生每週 × 4D，0–3 分 ＋ 一句證據（證據上限 200 字）"
    >
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-xs font-bold text-black/50">
            班別
            <select
              value={classId}
              onChange={(e) => {
                setClassId(e.target.value);
                setStudentId('');
                setScores({});
                setEvidence({});
                setResult({ ok: [], fail: [] });
              }}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              data-testid="scores-class"
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
                setScores({});
                setEvidence({});
                setResult({ ok: [], fail: [] });
              }}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              disabled={!classId}
              data-testid="scores-student"
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
            週次
            <select
              value={weekNo}
              onChange={(e) => setWeekNo(Number(e.target.value))}
              className="mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm font-normal text-[#00023D]"
              data-testid="scores-week"
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
        {!roster.loading && !roster.error && roster.classes.length === 0 && (
          <p className="mt-4 text-sm text-black/40">你名下暫時未有班別。</p>
        )}
        {selected && (
          <p className="mt-3 text-xs text-black/40">
            學生代號 {mask(selected.student_id)} · 階段{' '}
            {selected.age_band ?? '—'} · 報告語言 {selected.lang_code}
          </p>
        )}
      </div>

      {selected && (
        <div className="mt-4 space-y-3">
          {DIMENSIONS.map((dim) => {
            const len = (evidence[dim.code] ?? '').length;
            return (
              <div
                key={dim.code}
                className="rounded-2xl border border-black/5 bg-white p-4 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-bold text-[#00023D]">{dim.name}</p>
                    <p className="text-[11px] text-black/35">{dim.code}</p>
                  </div>
                  <div className="flex gap-1" role="group" aria-label={`${dim.code} score`}>
                    {SCORE_OPTIONS.map((opt) => {
                      const active = scores[dim.code] === opt.value;
                      return (
                        <button
                          key={String(opt.value)}
                          type="button"
                          onClick={() =>
                            setScores((prev) => ({ ...prev, [dim.code]: opt.value }))
                          }
                          data-testid={`score-${dim.code}-${String(opt.value)}`}
                          className={`h-9 w-11 rounded-lg text-sm font-bold transition-colors ${
                            active
                              ? 'bg-[#00023D] text-white'
                              : 'bg-black/5 text-black/50 hover:bg-[#00023D]/15'
                          }`}
                        >
                          {opt.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <textarea
                  value={evidence[dim.code] ?? ''}
                  onChange={(e) =>
                    setEvidence((prev) => ({ ...prev, [dim.code]: e.target.value }))
                  }
                  maxLength={EVIDENCE_MAX_CHARS}
                  rows={2}
                  placeholder="一句證據（課堂上觀察到的事實）"
                  className="mt-3 w-full resize-none rounded-lg border border-black/10 px-3 py-2 text-sm"
                  data-testid={`evidence-${dim.code}`}
                />
                <p className="mt-1 text-right text-[11px] text-black/35">
                  {len}/{EVIDENCE_MAX_CHARS}
                </p>
              </div>
            );
          })}

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={save}
              disabled={saving || scores[DIMENSIONS[0].code] === undefined}
              className="rounded-full bg-[#00023D] px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
              data-testid="scores-save"
            >
              {saving ? '儲存中…' : '儲存本週評分'}
            </button>
            <span className="text-[11px] text-black/35">
              最高 {SCORE_MAX} 分；揀「—」＝撤回該維度評分
            </span>
          </div>

          {error && <p className="text-sm text-red-600">{error}</p>}
          {result.ok.length > 0 && (
            <p className="text-sm text-emerald-700">
              已儲存：{result.ok.join('、')}
            </p>
          )}
          {result.fail.length > 0 && (
            <ul className="text-sm text-red-600">
              {result.fail.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </TeacherConsoleFrame>
  );
}
