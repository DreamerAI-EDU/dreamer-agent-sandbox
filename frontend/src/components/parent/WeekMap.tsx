// Bridge-3b — Parent Console 8-week course map (GET /api/parent/curriculum).
//
// Layout:
//   WeekMap (this file)                  ← own fetch, own selected week
//   ├─ header: course title + current week chip
//   ├─ 8-cell grid: locked 灰 / active 藍 / completed 綠
//   └─ week detail (drill-in): backend-authored title + MasteryBar
//
// Discipline (same tradition as the kid badge / label_soften):
//   * `title` and `course_title` come from the backend verbatim (topic_metadata
//     is the SoT). The grid NEVER translates a topic_id — only the frame labels
//     (status words, "This week", "No data yet") are localized here.
//   * `mastery_pct` is raw 0..1 for MasteryBar. `null` means the week has no
//     data: render 未有數據 / No data yet — NEVER 0% (neutral, no invented
//     progress). A stored 0.0 is real data and is shown as 0%.
//   * `state: 'none'` is a normal 200 (no class / nothing mounted / non-linear
//     rows): show the neutral message, not an error.

import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { useLang } from '../../lib/i18n';
import type { ParentCurriculumResponse, ParentWeekStatus } from '../../lib/types';
import { MasteryBar } from './MasteryBar';

const STATUS_CELL: Record<ParentWeekStatus, string> = {
  locked: 'bg-black/5 text-black/40 ring-black/10',
  active: 'bg-[#00023D] text-white ring-[#00023D]/30',
  completed: 'bg-emerald-500 text-white ring-emerald-600/20',
};

const STATUS_DOT: Record<ParentWeekStatus, string> = {
  locked: 'bg-black/20',
  active: 'bg-[#00023D]',
  completed: 'bg-emerald-500',
};

const STATUS_ORDER: ParentWeekStatus[] = ['locked', 'active', 'completed'];

export function WeekMap({ studentId }: { studentId: string }) {
  const { copy } = useLang();
  const [data, setData] = useState<ParentCurriculumResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<number | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const resp = await api.parentCurriculum(studentId);
      setData(resp);
      // Land on the week the class is actually in; 'none' has nothing to open.
      setSelected(resp.state === 'none' ? null : resp.current_week);
      setError('');
    } catch (err) {
      // A failure here must not take the dashboard down: the report views
      // below stay usable, and the card shows the server wording verbatim.
      setData(null);
      setSelected(null);
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setLoading(false);
    }
  }, [copy.unexpectedError, studentId]);

  useEffect(() => {
    // load() only sets state after an await (async fetch), never synchronously.
    void load();
  }, [load]);

  const statusLabel = useCallback(
    (status: ParentWeekStatus) =>
      status === 'completed'
        ? copy.weekMapStatusCompleted
        : status === 'active'
          ? copy.weekMapStatusActive
          : copy.weekMapStatusLocked,
    [copy],
  );

  const selectedWeek = data?.weeks.find((w) => w.week_no === selected) ?? null;

  return (
    <div className="rounded-2xl border border-black/5 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[#00023D]">{copy.weekMapTitle}</h2>
          <p className="mt-0.5 text-xs text-black/40">
            {data?.course_title ? data.course_title : copy.weekMapSubtitle}
          </p>
        </div>
        {data && data.state !== 'none' && data.current_week !== null && (
          <span className="rounded-full border border-black/10 bg-[#f6f4ef] px-3 py-1 text-xs font-medium text-[#00023D]">
            {copy.weekMapCurrentWeek} {data.current_week} / {data.total_weeks}
          </span>
        )}
      </div>

      {loading && !data && <p className="mt-4 text-xs text-black/40">{copy.loading}</p>}

      {error && (
        <div className="mt-4 text-xs text-red-700">
          {error}
          <button type="button" onClick={() => void load()} className="ml-2 underline">
            {copy.retry}
          </button>
        </div>
      )}

      {data && data.state === 'none' && (
        <p className="mt-4 rounded-xl bg-[#f6f4ef] px-3 py-3 text-xs text-black/50">
          {copy.weekMapNeutral}
        </p>
      )}

      {data && data.state !== 'none' && data.weeks.length > 0 && (
        <>
          <div className="mt-4 grid grid-cols-4 gap-2 sm:grid-cols-8">
            {data.weeks.map((week) => {
              const isOpen = selected === week.week_no;
              return (
                <button
                  key={week.week_no}
                  type="button"
                  aria-pressed={isOpen}
                  title={week.title || `Week ${week.week_no}`}
                  onClick={() => setSelected(isOpen ? null : week.week_no)}
                  className={`flex flex-col items-center justify-center gap-0.5 rounded-xl px-2 py-2.5 ring-1 transition-all ${
                    STATUS_CELL[week.status]
                  } ${isOpen ? 'scale-[1.03] shadow-md' : ''}`}
                >
                  <span className="text-sm font-bold leading-none">{week.week_no}</span>
                  <span className="text-[10px] leading-tight opacity-80">
                    {statusLabel(week.status)}
                  </span>
                </button>
              );
            })}
          </div>

          <p className="mt-3 flex flex-wrap items-center gap-3 text-[10px] text-black/40">
            {STATUS_ORDER.map((status) => (
              <span key={status} className="flex items-center gap-1">
                <span className={`h-2 w-2 rounded-full ${STATUS_DOT[status]}`} />
                {statusLabel(status)}
              </span>
            ))}
          </p>

          {selectedWeek && (
            <div className="mt-4 rounded-xl border border-black/5 bg-[#f6f4ef] px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                {/* backend-authored text, rendered verbatim */}
                <p className="text-sm font-medium text-[#00023D]">
                  {selectedWeek.title || `${copy.weekMapTitle} · ${selectedWeek.week_no}`}
                </p>
                <span className="text-[10px] text-black/45">
                  {statusLabel(selectedWeek.status)}
                </span>
              </div>
              {selectedWeek.mastery_pct === null ? (
                // neutral: no data for this week — never render 0%
                <p className="mt-2 text-xs text-black/40">{copy.weekMapNoData}</p>
              ) : (
                <MasteryBar
                  mastery={selectedWeek.mastery_pct}
                  label={`${Math.round(selectedWeek.mastery_pct * 100)}%`}
                  title={copy.weekMapMastery}
                  className="mt-2"
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
