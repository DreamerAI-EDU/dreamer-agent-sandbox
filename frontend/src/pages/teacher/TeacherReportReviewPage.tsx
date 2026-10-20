// PR-5 A4 + A5 — review / edit a draft, then approve or reject.
//
// A4: only `pending_review` is editable. Every save goes through
//     PUT /api/teacher/reports/{id} with {edits:[{field,before,after}],
//     payload_patch} — the server appends to teacher_edits (append-only
//     trigger, phase8j), so the UI never claims to "overwrite" history.
//     The field editor is limited to the narrative paragraph (`content`);
//     descriptor sentences are display-only — they come from
//     config/report_descriptors.json via PR-4 and must not be rewritten here.
// A5: approve / reject buttons. An illegal transition answers 409 with a
//     readable error — shown verbatim, never swallowed.

import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router';
import { api, ApiError } from '../../lib/api';
import type { ReportDetail } from '../../lib/reportTypes';
import { DIMENSIONS, bandLabel, levelLabel, toReportLang } from '../../lib/parentReportCopy';
import { TeacherConsoleFrame } from './TeacherConsoleFrame';
import { mask } from '../../hooks/useTeacherRoster';

const STATUS_LABEL: Record<string, string> = {
  pending_review: '待審',
  approved: '已批核',
  rejected: '已駁回',
  superseded: '已被取代',
};

export function TeacherReportReviewPage() {
  const { reportId = '' } = useParams();
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [draftText, setDraftText] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const resp = await api.teacherReportDetail(reportId);
      setDetail(resp);
      setDraftText(resp.payload?.content ?? '');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '載入失敗');
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    if (!detail) return;
    setNotice('');
    setError('');
    const before = detail.payload?.content ?? '';
    if (draftText === before) {
      setNotice('內容未改動，唔需要儲存。');
      return;
    }
    setSaving(true);
    try {
      const resp = await api.teacherReportUpdate(detail.report_id, {
        edits: [{ field: 'content', before, after: draftText }],
        payload_patch: { content: draftText },
      });
      setDetail(resp);
      setDraftText(resp.payload?.content ?? '');
      setNotice('已儲存（另加一筆 teacher_edits 審計記錄）');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError('儲存失敗');
      }
    } finally {
      setSaving(false);
    }
  };

  const decide = async (kind: 'approve' | 'reject') => {
    if (!detail) return;
    setNotice('');
    setError('');
    setSaving(true);
    try {
      const resp =
        kind === 'approve'
          ? await api.teacherReportApprove(detail.report_id, note || undefined)
          : await api.teacherReportReject(detail.report_id, note || undefined);
      setDetail(resp);
      setNotice(kind === 'approve' ? '已批准並發佈' : '已駁回');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '操作失敗');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <TeacherConsoleFrame title="審閱報告" subtitle="載入中…">
        <p className="text-sm text-black/40">載入報告…</p>
      </TeacherConsoleFrame>
    );
  }

  if (error && !detail) {
    return (
      <TeacherConsoleFrame title="審閱報告" subtitle="無法載入">
        <p className="text-sm text-red-600" data-testid="review-error">
          {error}
        </p>
      </TeacherConsoleFrame>
    );
  }

  if (!detail) {
    return (
      <TeacherConsoleFrame title="審閱報告" subtitle="找不到報告">
        <p className="text-sm text-black/40">報告唔存在。</p>
      </TeacherConsoleFrame>
    );
  }

  const lang = toReportLang(detail.lang_code);
  const editable = detail.status === 'pending_review';
  const descriptors = detail.payload?.report?.dimension_descriptors ?? {};

  return (
    <TeacherConsoleFrame
      title={`審閱報告 v${detail.version}`}
      subtitle={`學生 ${mask(detail.student_id)} · W${detail.week_from}–W${detail.week_to} · ${detail.lang_code}`}
    >
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span
            className={`rounded-full px-2 py-0.5 font-bold ${
              detail.status === 'pending_review'
                ? 'bg-amber-100 text-amber-800'
                : detail.status === 'approved'
                  ? 'bg-emerald-100 text-emerald-800'
                  : 'bg-black/10 text-black/50'
            }`}
            data-testid="review-status"
          >
            {STATUS_LABEL[detail.status] ?? detail.status}
          </span>
          <span className="text-black/40">階段 {bandLabel(detail.age_band, lang)}</span>
          <span className="text-black/40">版本 v{detail.version}</span>
          <span className="text-black/40">審計記錄 {detail.teacher_edits_count} 筆</span>
          <span className="text-black/30">report_id {detail.report_id.slice(0, 8)}…</span>
        </div>
        {!editable && (
          <p className="mt-3 rounded-lg bg-black/[0.03] px-3 py-2 text-xs text-black/50">
            只有待審（pending_review）報告可以修改；呢份報告現時係「
            {STATUS_LABEL[detail.status] ?? detail.status}」，以下內容唯讀。
          </p>
        )}
      </div>

      {/* A4 descriptor panel — band × lang sentences, verbatim from PR-4 JSON */}
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-bold text-[#00023D]">四維度等級句（對照用）</h2>
        <p className="mt-1 text-[11px] text-black/35">
          等級句由後端按 band × lang 提供，屬凍結內容，前端只顯示、不可改寫。
        </p>
        <ul className="mt-3 space-y-2" data-testid="review-descriptors">
          {DIMENSIONS.map((dim) => {
            const score = detail.scores?.[dim.code];
            const sentence = descriptors[dim.code];
            return (
              <li key={dim.code} className="rounded-xl bg-black/[0.02] px-3 py-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-bold text-[#00023D]">{dim.name}</span>
                  <span className="rounded-full bg-[#00023D]/10 px-2 py-0.5 text-[11px] font-bold text-[#00023D]">
                    {score === null || score === undefined
                      ? '未評分'
                      : `${score} · ${levelLabel(score, lang)}`}
                  </span>
                </div>
                <p className="mt-1 text-xs leading-relaxed text-black/60">
                  {sentence ?? '（此報告生成時未有等級句資料）'}
                </p>
              </li>
            );
          })}
        </ul>
      </div>

      {/* A4 field-level editor */}
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-bold text-[#00023D]">報告正文</h2>
        <p className="mt-1 text-[11px] text-black/35">
          每次儲存會新增一筆 {`{field, before, after, by, at}`} 記錄（append-only，不可覆寫歷史）。
        </p>
        <textarea
          value={draftText}
          onChange={(e) => setDraftText(e.target.value)}
          readOnly={!editable}
          rows={6}
          className="mt-3 w-full resize-y rounded-lg border border-black/10 px-3 py-2 text-sm leading-relaxed read-only:bg-black/[0.02]"
          data-testid="review-content"
        />
        {editable && (
          <button
            type="button"
            onClick={save}
            disabled={saving}
            className="mt-3 rounded-full bg-[#00023D] px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
            data-testid="review-save"
          >
            {saving ? '儲存中…' : '儲存修改'}
          </button>
        )}
      </div>

      {/* A5 decisions */}
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <h2 className="text-sm font-bold text-[#00023D]">批核決定</h2>
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          placeholder="備註（可留空）"
          className="mt-3 w-full resize-none rounded-lg border border-black/10 px-3 py-2 text-sm"
          data-testid="review-note"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => decide('approve')}
            disabled={!editable || saving}
            className="rounded-full bg-emerald-600 px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
            data-testid="review-approve"
          >
            批准並發佈
          </button>
          <button
            type="button"
            onClick={() => decide('reject')}
            disabled={!editable || saving}
            className="rounded-full bg-red-600 px-5 py-2 text-sm font-bold text-white disabled:opacity-40"
            data-testid="review-reject"
          >
            駁回
          </button>
          {!editable && (
            <span className="self-center text-[11px] text-black/35">
              非待審狀態不可再批核／駁回（後端會回 409）。
            </span>
          )}
        </div>
        {notice && (
          <p className="mt-3 text-sm text-emerald-700" data-testid="review-notice">
            {notice}
          </p>
        )}
        {error && (
          <p className="mt-3 text-sm text-red-600" data-testid="review-error">
            {error}
          </p>
        )}
      </div>
    </TeacherConsoleFrame>
  );
}
