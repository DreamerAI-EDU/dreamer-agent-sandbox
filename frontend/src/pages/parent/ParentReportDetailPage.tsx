// PR-5 B2 — single approved report, read-only. PR-6 §A1-4 makes it BILINGUAL:
// every line renders EN first and the family's Chinese (繁 for zh-hk / en, 簡
// for zh-cn) underneath. Nothing else about the surface changed.
//
// Everything visible is either a frozen string (PARENT_REPORT_COPY / BAND_LABELS
// / LEVEL_LABELS, all three languages already in parentReportCopy.ts) or copied
// verbatim out of the payload returned by
// GET /api/parent/reports?student_id=…&report_id=…:
//   * `payload.content`               — the narrative paragraph (ONE language)
//   * `descriptor_pairs[code]`        — PR-6: both language cells of the SAME
//                                      144-table descriptor cell, derived
//                                      server-side from the stored scores
//   * `payload.report.dimension_descriptors` — pre-PR-6 rows: one language only
//   * `report.topics[].last_label_parent` / `.recent_evidence[].evidence_text`
// Numeric mastery is the payload's 0..1 value × 100 — no local re-scoring.
//
// 零新措辭: the bilingual pairs are two frozen cells, never a translation. Free
// text (narrative / evidence) is single-language by design — 禁機翻.
//
// Red lines: no edit controls, no approve/reject, the raw band code is never
// rendered (§B3), and no internal key (`mode` / `variant`) is ever printed.
//
// PR-6 B5 lifts the old "no PDF button" note: one approved-only download per
// role, and this page owns the parent one. The button label is the technical
// token `PDF` — deliberately NOT a new sentence (零新措辭), and a failed
// download stays client-side silent (a parent-visible error line would be new
// wording needing its own 申報).

import { useCallback, useEffect, useState } from 'react';
import { Link, Navigate, useParams, useSearchParams } from 'react-router';
import { api, ApiError } from '../../lib/api';
import {
  DIMENSIONS,
  LEVEL_LABELS,
  PARENT_REPORT_COPY,
  bandLabel,
  toReportLang,
  type ReportLang,
} from '../../lib/parentReportCopy';
import { formatDuration, masteryToPercent } from '../../lib/parentTypes';
import { AppShell } from '../../components/AppShell';
import { useParentReportsGuard } from '../../hooks/useParentReportsGuard';
import type { ParentReportDetailResponse } from '../../lib/reportTypes';

/** EN on top, Chinese underneath — the §A1-4 stack, used for every chrome word.
 *
 *  One exception, and it is a rendering rule rather than new wording: a few
 *  frozen cells are literally identical in EN and zh (e.g.
 *  ``PARENT_REPORT_COPY.*.dimensions`` is `4 Dimension Evaluation` in all three
 *  languages). Printing the same string twice reads as a bug, so an identical
 *  pair collapses to a single line — nothing is translated, invented or dropped.
 */
function Bi({ en, zh, className }: { en: string; zh: string; className?: string }) {
  return (
    <span className={className}>
      <span className="block">{en}</span>
      {zh !== en && (
        <span className="block text-[11px] font-normal text-black/45">{zh}</span>
      )}
    </span>
  );
}

/** One frozen level label -> the same level in both languages (0 new wording).
 *  Returns null when the stored label is not one of the frozen §三 names, in
 *  which case the caller prints it once, exactly as stored. */
function levelPair(
  label: string,
  lang: ReportLang,
): { en: string; zh: string } | null {
  const zhLang: ReportLang = lang === 'zh-cn' ? 'zh-cn' : 'zh-hk';
  for (const code of [3, 2, 1, 0]) {
    if (LEVEL_LABELS[lang][code] === label) {
      return { en: LEVEL_LABELS.en[code], zh: LEVEL_LABELS[zhLang][code] };
    }
  }
  return null;
}

export function ParentReportDetailPage() {
  const guard = useParentReportsGuard();
  const { reportId = '' } = useParams();
  const [params] = useSearchParams();
  const [detail, setDetail] = useState<ParentReportDetailResponse['report'] | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState(false);
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
  // A1: en -> EN + 繁; zh-hk -> 繁 + EN; zh-cn -> 簡 + EN. `zh` is the Chinese
  // side of the stack, `en` the English side.
  const zhLang: ReportLang = lang === 'zh-cn' ? 'zh-cn' : 'zh-hk';
  const copy = PARENT_REPORT_COPY[lang];
  const en = PARENT_REPORT_COPY.en;
  const zh = PARENT_REPORT_COPY[zhLang];

  const download = useCallback(async () => {
    if (!studentId || !reportId) return;
    setDownloading(true);
    try {
      const blob = await api.parentReportPdf(studentId, reportId);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      // Mirror the server's `content-disposition` name (`dreamer-report-<8>`),
      // so the file a parent sees on disk matches what the download endpoint says.
      anchor.download = `dreamer-report-${reportId.slice(0, 8)}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      // Deliberately no parent-visible copy here (零新措辭) — surface failures
      // to the console only; the server-side wording is already logged.
      console.warn('report pdf download failed', err);
    } finally {
      setDownloading(false);
    }
  }, [studentId, reportId]);

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
  const pairs = detail?.descriptor_pairs;

  return (
    <AppShell user={guard.user}>
      <div className="space-y-4" data-testid="parent-report-detail">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link
            to={`/parent/reports?student=${encodeURIComponent(studentId)}`}
            className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-bold text-black/50 hover:bg-[#00023D]/10"
            data-testid="parent-back"
          >
            ← {en.backToList} / {zh.backToList}
          </Link>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void download()}
              disabled={downloading || !detail}
              className="rounded-full bg-[#00023D] px-3 py-1.5 text-xs font-bold text-white disabled:opacity-40"
              data-testid="parent-report-pdf"
            >
              PDF
            </button>
            <span className="rounded-full bg-black/5 px-3 py-1 text-[11px] font-bold text-black/45">
              {en.readOnly} / {zh.readOnly}
            </span>
          </div>
        </div>

        {loading && <p className="text-sm text-black/40">{copy.loading}</p>}
        {!loading && error && <p className="text-sm text-red-600">{copy.notFound}</p>}

        {detail && inner && (
          <>
            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">
                <span className="block">
                  {en.weekRange} {detail.week_from}–{detail.week_to}
                </span>
                <span className="mt-0.5 block text-base font-normal text-black/50">
                  {zh.weekRange} {detail.week_from}–{detail.week_to}
                </span>
              </h1>
              <div className="mt-1 space-y-0.5 text-xs text-black/45">
                <p>
                  {en.band} {bandLabel(detail.age_band, 'en')} · {en.lang}{' '}
                  {detail.lang_code} · {en.version} v{detail.version} · {en.published}{' '}
                  {detail.published_at.slice(0, 10)}
                </p>
                <p>
                  {zh.band} {bandLabel(detail.age_band, zhLang)} · {zh.lang}{' '}
                  {detail.lang_code} · {zh.version} v{detail.version} · {zh.published}{' '}
                  {detail.published_at.slice(0, 10)}
                </p>
              </div>
              {detail.payload?.content && (
                <div className="mt-4" data-testid="parent-narrative">
                  <h2 className="text-sm font-bold text-[#00023D]">
                    <Bi en={en.narrative} zh={zh.narrative} />
                  </h2>
                  {/* Free text — single language, never machine-translated. */}
                  <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-black/70">
                    {detail.payload.content}
                  </p>
                </div>
              )}
            </div>

            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-[#00023D]">
                <Bi en={en.summary} zh={zh.summary} />
              </h2>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
                <div>
                  <dt className="text-[11px] text-black/40">
                    {en.sessions} / {zh.sessions}
                  </dt>
                  <dd className="font-bold text-[#00023D]">{inner.summary.session_count}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-black/40">
                    {en.minutes} / {zh.minutes}
                  </dt>
                  <dd className="font-bold text-[#00023D]">
                    {formatDuration(inner.summary.total_duration_seconds) ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-[11px] text-black/40">
                    {en.topics} / {zh.topics}
                  </dt>
                  <dd className="font-bold text-[#00023D]">{inner.summary.topics_touched}</dd>
                </div>
              </dl>
            </div>

            <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
              <h2 className="text-sm font-bold text-[#00023D]">
                <Bi en={en.dimensions} zh={zh.dimensions} />
              </h2>
              <ul className="mt-3 space-y-2" data-testid="parent-dimensions">
                {DIMENSIONS.map((dim) => {
                  const pair = pairs?.[dim.code];
                  return (
                    <li key={dim.code} className="rounded-xl bg-black/[0.02] px-3 py-2">
                      <p className="text-sm font-bold text-[#00023D]">{dim.name}</p>
                      {pair ? (
                        <div
                          className="mt-0.5 space-y-0.5 text-xs leading-relaxed text-black/60"
                          data-testid={`parent-descriptor-${dim.code}`}
                        >
                          <p>{pair.en}</p>
                          <p>{pair.zh}</p>
                        </div>
                      ) : (
                        <p className="mt-0.5 text-xs leading-relaxed text-black/60">
                          {descriptors[dim.code] ?? '—'}
                        </p>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>

            {inner.topics.length > 0 && (
              <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
                <h2 className="text-sm font-bold text-[#00023D]">
                  <Bi en={en.topicsTitle} zh={zh.topicsTitle} />
                </h2>
                <ul className="mt-3 space-y-3" data-testid="parent-topics">
                  {inner.topics.map((topic) => {
                    const pct = masteryToPercent(topic.mastery_pct);
                    const level = topic.last_label_parent
                      ? levelPair(topic.last_label_parent, lang)
                      : null;
                    return (
                      <li key={topic.topic_id} className="rounded-xl bg-black/[0.02] px-3 py-2">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-sm font-bold text-[#00023D]">{topic.subject}</p>
                          <span className="rounded-full bg-[#00023D]/10 px-2 py-0.5 text-[11px] font-bold text-[#00023D]">
                            {en.mastery} {zh.mastery} {pct === null ? '—' : `${pct} / 100`}
                          </span>
                        </div>
                        {topic.last_label_parent && (
                          <p className="mt-1 text-xs text-black/60">
                            {level ? (
                              <>
                                {level.en} / {level.zh}
                              </>
                            ) : (
                              topic.last_label_parent
                            )}
                          </p>
                        )}
                        {topic.recent_evidence.length > 0 && (
                          <div className="mt-2 space-y-1">
                            <p className="text-[11px] font-bold text-black/35">
                              {en.evidence} / {zh.evidence}
                            </p>
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
