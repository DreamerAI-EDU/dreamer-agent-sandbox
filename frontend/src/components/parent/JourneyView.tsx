// W3-B — Journey view (period=journey).
//
// Whole-journey retrospective: activity timeline (daily session counts) plus
// per-topic mastery across the entire history. Empty state is friendly —
// new students still land in First Steps variant (see FirstStepsView).

import type {
  ParentReportPeriod,
  ParentReportTopic,
  ParentTimelineEntry,
} from '../../lib/parentTypes';
import { MasteryBar } from './MasteryBar';
import { DeltaBadge } from './DeltaBadge';

interface JourneyViewProps {
  period: ParentReportPeriod;
  timeline: ParentTimelineEntry[];
  topics: ParentReportTopic[];
}

export function JourneyView({ period, timeline, topics }: JourneyViewProps) {
  const dayCount = period.days;
  return (
    <section className="space-y-4">
      <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
        <p className="mb-1 text-xs uppercase tracking-wide text-black/40">成長旅程</p>
        <p className="text-sm text-black/70">
          累計旅程 {dayCount} 天 · 記錄 {timeline.length} 天有學習活動
        </p>
        {timeline.length === 0 && (
          <p className="mt-3 text-sm text-black/40">旅程尚未開始，完成第一次學習後會喺度顯示。</p>
        )}
        {timeline.length > 0 && (
          <ul className="mt-4 space-y-1.5">
            {timeline.slice(-14).map((day) => (
              <li key={day.date} className="flex items-center gap-3 text-sm">
                <span className="w-24 shrink-0 text-xs text-black/50">{day.date}</span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-black/5">
                  <div
                    className="h-full rounded-full bg-[#00023D]/70"
                    style={{
                      width: `${Math.min(100, (day.sessions / Math.max(1, timeline.reduce((m, d) => Math.max(m, d.sessions), 0))) * 100)}%`,
                    }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right text-xs text-black/60">
                  {day.sessions} 次{day.modes.length > 0 ? ` · ${day.modes.join('/')}` : ''}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>

      {topics.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs uppercase tracking-wide text-black/40">歷程主題掌握度</p>
          <ul className="space-y-5">
            {topics.map((topic) => (
              <li key={topic.topic_id}>
                <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                  <span className="text-sm font-medium text-black/80">{topic.subject}</span>
                  <div className="flex items-center gap-2">
                    <DeltaBadge delta={topic.mastery_delta} />
                    <span className="text-xs text-black/60">{topic.last_label_parent}</span>
                  </div>
                </div>
                <MasteryBar
                  mastery={topic.mastery_pct}
                  label={`${Math.round(topic.mastery_pct * 100)}%`}
                />
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
