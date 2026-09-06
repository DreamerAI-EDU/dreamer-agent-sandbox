// W3-B — Cycle report (period=cycle, standard variant focus).
//
// Main in-depth report: summary stats, per-topic mastery cards (progress
// bar + independent delta badge + backend kid-facing label), narrative
// digest, portfolio cross-links and cost summary (no_data → 「暫無數據」).

import type { ParentReportEnvelope } from '../../lib/parentTypes';
import { DurationDisplay } from './DurationDisplay';
import { MasteryBar } from './MasteryBar';
import { DeltaBadge } from './DeltaBadge';

interface CycleReportProps {
  envelope: ParentReportEnvelope;
}

export function CycleReport({ envelope }: CycleReportProps) {
  const { report, content, cost_summary } = envelope;
  const { summary, topics, period, portfolio_highlights } = report;
  const range = [period.from, period.to].filter(Boolean).join(' 至 ');

  const costText =
    cost_summary.status === 'ok' ? `${cost_summary.total_tokens.toLocaleString()} tokens` : '暫無數據';

  return (
    <section className="space-y-4">
      {content && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-1 text-xs uppercase tracking-wide text-black/40">整體概覽</p>
          {range && <p className="mb-3 text-xs text-black/40">{range}</p>}
          <p className="whitespace-pre-line text-sm leading-relaxed text-black/80">{content}</p>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <p className="text-xs text-black/40">學習次數</p>
          <p className="mt-1 text-2xl font-semibold text-[#00023D]">{summary.session_count}</p>
        </div>
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <DurationDisplay seconds={summary.total_duration_seconds} label="學習時長" />
        </div>
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <p className="text-xs text-black/40">觸及主題</p>
          <p className="mt-1 text-2xl font-semibold text-[#00023D]">{summary.topics_touched}</p>
        </div>
        <div className="rounded-2xl border border-black/5 bg-white p-4">
          <p className="text-xs text-black/40">Token 用量</p>
          <p className="mt-1 text-sm font-medium text-black/70">{costText}</p>
        </div>
      </div>

      {topics.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs uppercase tracking-wide text-black/40">主題掌握度</p>
          <ul className="space-y-5">
            {topics.map((topic) => (
              <li key={topic.topic_id}>
                <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <span className="text-sm font-medium text-black/80">{topic.subject}</span>
                  <div className="flex items-center gap-2">
                    <DeltaBadge delta={topic.mastery_delta} />
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                      {topic.last_label_parent}
                    </span>
                  </div>
                </div>
                <MasteryBar
                  mastery={topic.mastery_pct}
                  label={`${Math.round(topic.mastery_pct * 100)}%`}
                  title={`${topic.attempt_count} 次嘗試`}
                />
                {topic.recent_evidence.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {topic.recent_evidence.slice(-2).map((ev, i) => (
                      <li key={i} className="text-xs text-black/50">
                        {ev.date} · {ev.label_parent}
                        {ev.evidence_text ? ` — ${ev.evidence_text}` : ''}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {portfolio_highlights.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-2 text-xs uppercase tracking-wide text-black/40">作品集亮點</p>
          <ul className="space-y-1 text-sm text-black/70">
            {portfolio_highlights.map((h) => (
              <li key={h.id}>{h.title}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
