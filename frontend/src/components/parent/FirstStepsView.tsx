// W3-B — First Steps view (variant=first_steps).
//
// Driven by report.variant === 'first_steps': shows the starting baseline
// (first DIRECT assessment) and the Curriculum Navigator roadmap suggestions.
// Rendering rules: backend parent-facing labels (label_parent / action) are
// used verbatim — the front end never translates. No mastery deep-dive cards
// are forced on a student with fewer than ~5 sessions.

import type { ParentBaseline, ParentReportTopic, ParentRoadmapStep } from '../../lib/parentTypes';
import { MasteryBar } from './MasteryBar';

interface FirstStepsViewProps {
  digest: string;
  baseline: ParentBaseline | null;
  roadmap: ParentRoadmapStep[] | null;
  topics: ParentReportTopic[];
}

export function FirstStepsView({ digest, baseline, roadmap, topics }: FirstStepsViewProps) {
  return (
    <section className="space-y-4">
      <div className="rounded-2xl bg-[#00023D] p-5 text-white shadow-sm">
        <p className="mb-2 text-xs uppercase tracking-wide text-white/60">First Steps · 起步階段</p>
        <p className="whitespace-pre-line text-sm leading-relaxed text-white/90">
          {digest || '歡迎嚟到 Dreamer AI！完成第一次學習後，我哋會話你知小朋友嘅起步點。'}
        </p>
      </div>

      {baseline && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-1 text-xs uppercase tracking-wide text-black/40">起步點</p>
          <p className="text-sm text-black/80">
            {baseline.date} · {baseline.subject} —{' '}
            <span className="font-medium text-[#00023D]">{baseline.label_parent}</span>
          </p>
          <div className="mt-3">
            <MasteryBar mastery={baseline.confidence} title="起始信心度" />
          </div>
        </div>
      )}

      {roadmap && roadmap.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs uppercase tracking-wide text-black/40">下一步建議</p>
          <ul className="space-y-2.5">
            {roadmap.map((step) => (
              <li key={step.topic_id} className="flex items-start gap-3 text-sm">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-[#00023D]" aria-hidden />
                <div>
                  <p className="font-medium text-black/80">{step.topic_name}</p>
                  <p className="text-black/60">{step.action}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {topics.length > 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
          <p className="mb-3 text-xs uppercase tracking-wide text-black/40">已開始嘅主題</p>
          <ul className="space-y-4">
            {topics.map((topic) => (
              <li key={topic.topic_id}>
                <div className="mb-1 flex items-center justify-between text-sm">
                  <span className="font-medium text-black/80">{topic.subject}</span>
                  <span className="text-xs text-black/60">{topic.last_label_parent}</span>
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
