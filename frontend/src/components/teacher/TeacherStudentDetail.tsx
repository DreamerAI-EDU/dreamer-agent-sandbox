// W3-B 步骤 3 — Teacher-view student detail.
//
// Deep link: /teacher?class=<classId>&student=<maskId>&period=<period>.
// Rendered inside TeacherDashboard. SAME canonical Parent Report data
// (same-source parity, acceptance 3.5) wrapped for a TEACHING audience:
//   - session engagement (duration / frequency from summary + timeline)
//   - topic mastery with attempt/streak signals (teaching planning)
//   - sanitised assessment-label evolution timeline (assessment_history)
// P-series red lines hold: internal_label / confidence / rubric_id never
// appear (backend strips them); cost_summary / citations are NOT rendered.

import { ConsentIndicator } from '../parent/ConsentIndicator';
import { MasteryBar } from '../parent/MasteryBar';
import { DeltaBadge } from '../parent/DeltaBadge';
import { DurationDisplay } from '../parent/DurationDisplay';
import { useTeacherStudentProgress } from '../../hooks/useTeacherProgress';
import { masteryToPercent } from '../../lib/parentTypes';
import { TEACHER_PERIODS, fmtActivityDate } from '../../lib/teacherTypes';
import type { ParentPeriod } from '../../lib/parentTypes';
import { copyEn as copy } from '../../lib/i18n';

interface TeacherStudentDetailProps {
  /** 8-char mask (never the full uuid). */
  studentMask: string;
  period: ParentPeriod;
  onPeriodChange: (period: ParentPeriod) => void;
  /** Back to the Class Lens (clears ?student). */
  onBackToClass: () => void;
}

const AGE_LABELS: Record<string, string> = {
  'P1-P3': 'P1–P3',
  'P4-P6': 'P4–P6',
  'S1-S3': 'S1–S3',
};

const PERIOD_LABELS: Record<ParentPeriod, string> = {
  weekly: 'Weekly',
  cycle: 'Cycle',
  journey: 'Journey',
};

export function TeacherStudentDetail({
  studentMask,
  period,
  onPeriodChange,
  onBackToClass,
}: TeacherStudentDetailProps) {
  const { loading, error, data, reload } = useTeacherStudentProgress(studentMask, period);

  return (
    <div className="space-y-5">
      {/* back */}
      <button
        type="button"
        onClick={onBackToClass}
        className="rounded-lg border border-black/10 bg-white px-3 py-1.5 text-sm text-black/60 transition-colors hover:bg-[#00023D]/15"
      >
        ← Back to class
      </button>

      {loading && !data && (
        <div className="rounded-2xl border border-black/5 bg-white px-5 py-10 text-center text-sm text-black/50">
          {copy.loading}
        </div>
      )}

      {error && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-8 text-center text-sm text-red-700">
          <p>{error}</p>
          <button type="button" onClick={reload} className="mt-3 underline">
            {copy.retry}
          </button>
        </div>
      )}

      {data && (
        <>
          {/* identity + period switch */}
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">
                {data.student.display_name}
              </h1>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {data.student.age_band && (
                  <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                    {AGE_LABELS[data.student.age_band] ?? data.student.age_band}
                  </span>
                )}
                <ConsentIndicator status={data.student.media_consent} label="Media" />
              </div>
            </div>

            <div className="flex items-center gap-1 rounded-full border border-black/10 bg-white p-1">
              {TEACHER_PERIODS.map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => onPeriodChange(p)}
                  className={`rounded-full px-3 py-1.5 text-xs font-medium transition-colors ${
                    p === period
                      ? 'bg-[#00023D] text-white'
                      : 'text-black/60 hover:bg-[#00023D]/15'
                  }`}
                >
                  {PERIOD_LABELS[p]}
                </button>
              ))}
            </div>
          </div>

          {/* overall digest (same source as the parent lens) */}
          <div className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-black/70">Overall summary</h2>
            <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-black/70">
              {data.report.content || 'No summary available yet.'}
            </p>
          </div>

          {/* session engagement */}
          <section className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-black/70">Session engagement</h2>
            <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-black/[0.03] px-4 py-3">
                <p className="text-xs text-black/50">Sessions</p>
                <p className="mt-0.5 text-xl font-semibold text-black/80">
                  {data.report.report.summary.session_count}
                </p>
              </div>
              <div className="rounded-xl bg-black/[0.03] px-4 py-3">
                <p className="text-xs text-black/50">Topics touched</p>
                <p className="mt-0.5 text-xl font-semibold text-black/80">
                  {data.report.report.summary.topics_touched}
                </p>
              </div>
              <div className="rounded-xl bg-black/[0.03] px-4 py-3">
                <DurationDisplay seconds={data.report.report.summary.total_duration_seconds} label="Recorded time" />
              </div>
            </div>

            {data.report.report.activity_timeline.length > 0 && (
              <div className="mt-4 border-t border-black/5 pt-3">
                <p className="text-xs font-medium text-black/50">Session frequency</p>
                <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
                  {data.report.report.activity_timeline.map((t) => (
                    <li key={t.date} className="flex items-center justify-between text-xs text-black/60">
                      <span className="text-black/45">{t.date}</span>
                      <span>
                        {t.sessions} session{t.sessions === 1 ? '' : 's'}
                        {t.modes.length > 0 ? ` · ${t.modes.join('/')}` : ''}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          {/* topic mastery — teaching planning signal */}
          <section className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-black/70">Topic mastery</h2>
            {data.report.report.topics.length === 0 ? (
              <p className="mt-3 text-sm text-black/40">No topic snapshots in this period yet.</p>
            ) : (
              <div className="mt-3 space-y-4">
                {data.report.report.topics.map((topic) => {
                  const pct = masteryToPercent(topic.mastery_pct);
                  return (
                    <div key={topic.topic_id} className="border-t border-black/5 pt-3 first:border-0 first:pt-0">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-black/80">{topic.subject}</span>
                          <span className="text-xs text-black/40">{topic.topic_id}</span>
                          {topic.last_label_parent && (
                            <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                              {topic.last_label_parent}
                            </span>
                          )}
                          <DeltaBadge delta={topic.mastery_delta} />
                        </div>
                        <span className="text-xs text-black/50">
                          {topic.attempt_count} attempt{topic.attempt_count === 1 ? '' : 's'}
                          {topic.streak > 0 ? ` · streak ${topic.streak}` : ''}
                        </span>
                      </div>
                      <div className="mt-2 max-w-md">
                        <MasteryBar
                          mastery={topic.mastery_pct}
                          title="Mastery"
                          label={pct === null ? 'no data' : `${pct}%`}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          {/* assessment label evolution */}
          <section className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
            <h2 className="text-sm font-semibold text-black/70">Assessment history</h2>
            {data.assessment_history.length === 0 ? (
              <p className="mt-3 text-sm text-black/40">No assessments recorded yet.</p>
            ) : (
              <ol className="mt-4 space-y-0">
                {[...data.assessment_history].reverse().map((entry, i) => (
                  <li key={`${entry.date}-${i}`} className="relative border-l border-black/10 pb-4 pl-4 last:pb-0">
                    <span
                      className="absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full bg-[#00023D]"
                      aria-hidden
                    />
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs text-black/45">{fmtActivityDate(entry.date)}</span>
                      <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">{entry.subject}</span>
                      <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/50">{entry.mode}</span>
                    </div>
                    <p className="mt-1 text-sm text-black/75">{entry.label_parent || '—'}</p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      )}
    </div>
  );
}
