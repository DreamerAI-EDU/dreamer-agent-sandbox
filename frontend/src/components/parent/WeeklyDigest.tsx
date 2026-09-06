// W3-B — Weekly digest card (period=weekly).
//
// Lightweight summary: backend narrative digest + headline numbers.
// Reuses DurationDisplay (null → 「暫無數據」, never a fake 0) and shows the
// top recent topics with MasteryBar + DeltaBadge.

import type {
  ParentReportPeriod,
  ParentReportSummary,
  ParentReportTopic,
} from '../../lib/parentTypes';
import { DurationDisplay } from './DurationDisplay';
import { MasteryBar } from './MasteryBar';
import { DeltaBadge } from './DeltaBadge';

interface WeeklyDigestProps {
  /** Backend narrative digest (envelope.content) — shown verbatim. */
  digest: string;
  period: ParentReportPeriod;
  summary: ParentReportSummary;
  topics: ParentReportTopic[];
}

export function WeeklyDigest({ digest, period, summary, topics }: WeeklyDigestProps) {
  const range = [period.from, period.to].filter(Boolean).join(' 至 ');
  const top = topics.slice(0, 3);

  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs uppercase tracking-wide text-black/40">本週摘要</p>
        {range && <p className="mb-3 text-xs text-black/40">{range}</p>}
        {digest ? (
          <p className="whitespace-pre-line text-sm leading-relaxed text-black/80">{digest}</p>
        ) : (
          <p className="text-sm text-black/40">暫無數據</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <p className="text-xs text-black/40">學習次數</p>
          <p className="mt-1 text-2xl font-semibold text-[#00023D]">
            {summary.session_count}
          </p>
        </div>
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <DurationDisplay seconds={summary.total_duration_seconds} label="學習時長" />
        </div>
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <p className="text-xs text-black/40">觸及主題</p>
          <p className="mt-1 text-2xl font-semibold text-[#00023D]">
            {summary.topics_touched}
          </p>
        </div>
      </div>

      {top.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs uppercase tracking-wide text-black/40">近期主題</p>
          <ul className="space-y-4">
            {top.map((topic) => (
              <li key={topic.topic_id}>
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="text-sm font-medium text-black/80">{topic.subject}</span>
                  <div className="flex items-center gap-2">
                    <DeltaBadge delta={topic.mastery_delta} />
                    <span className="text-xs text-black/60">{topic.last_label_parent}</span>
                  </div>
                </div>
                <MasteryBar mastery={topic.mastery_pct} label={`${Math.round(topic.mastery_pct * 100)}%`} />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
