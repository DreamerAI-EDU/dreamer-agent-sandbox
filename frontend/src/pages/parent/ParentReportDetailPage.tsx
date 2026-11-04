// PR-5 B2 — single approved report, read-only, ONE language (§4.3).
//
// Everything visible is either a frozen §三 string (bandLabel / levelLabel /
// PARENT_REPORT_COPY) or copied verbatim out of the payload returned by
// GET /api/parent/reports?student_id=…&report_id=…:
//   * `payload.content`            — the narrative paragraph
//   * `report.dimension_descriptors` — PR-4 descriptor sentences (never edited
//                                    or translated here)
//   * `report.topics[].last_label_parent` / `.recent_evidence[].evidence_text`
// Numeric mastery is the payload's 0..1 value × 100 — no local re-scoring.
//
// Red lines: no edit controls, no approve/reject, no PDF button (§B5 — PR-6),
// and the raw band code is never rendered (§B3).
//
// P1 walkthrough fix (2026-10-20, commit on top of 8c1dd46): the "at a glance"
// grid used to print `payload.mode` (value `parent_report`) in a parent-visible
// tile — an internal envelope enum leaking onto the parent surface. That tile is
// gone; `copy.narrative` (frozen §三 chrome word) now heads the narrative
// paragraph instead, which is the only place that sentence belongs. Nothing in
// this file may render `payload.mode` / `report.variant` / any internal key.

import { useCallback, useEffect, useState } from 'react';
import { Link, Navigate, useParams, useSearchParams } from 'react-router';
import { api, ApiError } from '../../lib/api';
import {
  DIMENSIONS,
  PARENT_REPORT_COPY,
  bandLabel,
  toReportLang,
} from '../../lib/parentReportCopy';
import { formatDuration, masteryToPercent } from '../../lib/parentTypes';
import { AppShell } from '../../components/AppShell';
import { useParentReportsGuard } from '../../hooks/useParentReportsGuard';
import type { ParentReportDetailResponse } from '../../lib/reportTypes';

export function ParentReportDetailPage() {
  const guard = useParentReportsGuard();
  const { reportId = '' } = useParams();
  const [params] = useSearchParams();
  const [detail, setDetail] = useState<ParentReportDetailResponse['report'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const queryStudent = (params.get('student') ?? '').trim();
  const fallbackStudent = guard.kind === 'ready' ? (guard.students[0]?.id ?? '') : '';
  const studentId = queryStudent || fallbackStudent;

  const load = useCallback(async (student: string, id: string) => {
    setLoading(true);
    setError('');
    try {
      const resp = await api.parentReportDetail(student, id);
      setDetail(resp.report);
    } catch (err) {
      setDetail(null);
      setError(err instanceof ApiError ? err.message : '');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!studentId || !reportId) return;
    void load(studentId, reportId);
  }, [studentId, reportId, load]);

  const lang = toReportLang(detail?.lang_code);
  const copy = PARENT_REPORT_COPY[lang];

  if (guard.kind === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }
  if (guard.kind === 'redirect') return <Navigate to={guard.to} replace />;
  if (guard.kind === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <p className="text-sm text-red-600">{guard.message}</p>
      </div>
    );
  }

  const inner = detail?.payload?.report;
  const descriptors = inner?.dimension_descriptors ?? {};

  return (
    <AppShell user={guard.user}>
      <div className="space-y-4" data-testid="parent-report-detail">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            to={`/parent/reports?student=${encodeURIComponent(studentId)}`}
            className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-bold text-black/50 hover:bg-[#00023D]/10"
            data-testid="parent-back"
          >
            ← {copy.backToList}
          </Link>
          <span className="rounded-full bg-black/5 px-3 py-1 text-[11px] font-bold text-black/45">
            {copy.readOnly}
          </span>
        </div>

        {loading && <p className="text-sm text-black/40">{copy.loading}</p>}
        {!loading && error && <p className="text-sm text-red-600">{copy.notFound}</p>}

        {detail && inner && (
          <>
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">
                {copy.weekRange} {detail.week_from}–{detail.week_to}
              </h1>
              <p className="mt-1 text-xs text-black/45">
                {copy.band} {bandLabel(detail.age_band, lang)} · {copy.lang}{' '}
                {detail.lang_code} · {copy.version} v{detail.version} · {copy.published}{' '}
                {detail.published_at.slice(0, 10)}
              </p>
              {detail.payload?.content && (
                <div className="mt-4" data-testid="parent-narrative">
                  <h2 className="text-sm font-bold text-[#00023D]">{copy.narrative}</h2>
                  <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-black/70">
                    {detail.payload.content}
                  </p>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-[#00023D]">{copy.summary}</h2>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-[11px] text-black/40">{copy.sessions}</dt>
                  <dd className="font-bold text-[#00023D]">{inner.summary.session_count}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-black/40">{copy.minutes}</dt>
                  <dd className="font-bold text-[#00023D]">
                    {formatDuration(inner.summary.total_duration_seconds) ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-black/40">{copy.topics}</dt>
                  <dd className="font-bold text-[#00023D]">{inner.summary.topics_touched}</dd>
                </div>
              </dl>
            </div>

            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-[#00023D]">{copy.dimensions}</h2>
              <ul className="mt-3 space-y-2" data-testid="parent-dimensions">
                {DIMENSIONS.map((dim) => (
                  <li key={dim.code} className="rounded-xl bg-black/[0.02] px-3 py-2">
                    <p className="text-sm font-bold text-[#00023D]">{dim.name}</p>
                    <p className="mt-0.5 text-xs leading-relaxed text-black/60">
                      {descriptors[dim.code] ?? '—'}
                    </p>
                  </li>
                ))}
              </ul>
            </div>

            {inner.topics.length > 0 && (
              <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-bold text-[#00023D]">{copy.topicsTitle}</h2>
                <ul className="mt-3 space-y-3" data-testid="parent-topics">
                  {inner.topics.map((topic) => {
                    const pct = masteryToPercent(topic.mastery_pct);
                    return (
                      <li key={topic.topic_id} className="rounded-xl bg-black/[0.02] px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-bold text-[#00023D]">{topic.subject}</p>
                          <span className="rounded-full bg-[#00023D]/10 px-2 py-0.5 text-[11px] font-bold text-[#00023D]">
                            {copy.mastery} {pct === null ? '—' : `${pct} / 100`}
                          </span>
                        </div>
                        {topic.last_label_parent && (
                          <p className="mt-1 text-xs text-black/60">{topic.last_label_parent}</p>
                        )}
                        {topic.recent_evidence.length > 0 && (
                          <div className="mt-2 space-y-1">
                            <p className="text-[11px] font-bold text-black/35">{copy.evidence}</p>
                            {topic.recent_evidence.map((ev, idx) => (
                              <p
                                key={`${topic.topic_id}-${idx}`}
                                className="text-[11px] leading-relaxed text-black/50"
                              >
                                {ev.date} {ev.evidence_text}
                              </p>
                            ))}
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
