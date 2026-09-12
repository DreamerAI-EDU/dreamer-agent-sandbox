// Bridge-3c — 進度 card (掣 4): the class's 8-week progress + 「下一週」.
//
//   GET  /api/classes/{id}/curriculum   -> the ONLY source of the week number,
//                                          the eight statuses and the class
//                                          mastery average (decision ④).
//   POST /api/classes/{id}/advance-week -> server closes the active week and
//                                          unlocks the next one in a single
//                                          transaction (409 when illegal).
//
// UI zero logic: nothing here counts weeks, decides what may be unlocked or
// averages mastery. The card renders the payload, and after a write it
// re-reads the same GET — so what the teacher sees is always the server's own
// state, never a locally predicted one. mastery_pct is the class average
// (mastery_scope='class') and stays null — rendered "No data yet" — when
// nobody in the class has data for that week; never an invented 0%.
//
// Teacher-facing UI is pinned to English (copyEn) — same policy as the rest
// of the teacher console (W3-C).

import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { copyEn as copy } from '../../lib/i18n';
import { masteryToPercent } from '../../lib/parentTypes';
import type { ClassCurriculumRow, ClassCurriculumResponse } from '../../lib/types';

interface CourseProgressCardProps {
  classId: string;
  /** A week was advanced — stats/roster may have moved too; let the page reload. */
  onAdvanced?: () => void;
}

/** Server status -> chip label. No derived states, no client-side locking. */
function statusLabel(status: ClassCurriculumRow['status']): string {
  if (status === 'locked') return copy.weekMapStatusLocked;
  if (status === 'active') return copy.weekMapStatusActive;
  return copy.weekMapStatusCompleted;
}

/** Raw 0..1 mastery (or null) -> the displayed string. null is "no data". */
function pctText(value: number | null): string {
  const pct = masteryToPercent(value);
  return pct === null ? copy.weekMapNoData : `${pct}%`;
}

export function CourseProgressCard({ classId, onAdvanced }: CourseProgressCardProps) {
  const [course, setCourse] = useState<ClassCurriculumResponse | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState('');

  const load = useCallback(async () => {
    try {
      const resp = await api.classCurriculum(classId);
      setCourse(resp);
      setError('');
    } catch (err) {
      // A failing read keeps the card honest: error + retry, never a guessed week.
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setLoaded(true);
    }
  }, [classId]);

  useEffect(() => {
    setLoaded(false);
    setCourse(null);
    setError('');
    setNote('');
    void load();
  }, [load]);

  const advance = async () => {
    setBusy(true);
    setError('');
    setNote('');
    try {
      await api.advanceWeek(classId);
      await load();
      setNote(copy.courseProgressAdvanced);
      onAdvanced?.();
    } catch (err) {
      // 409 (unmounted / gap / already past week 8) — server's own wording.
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const mounted = Boolean(course && course.state !== 'none');
  const currentRow =
    mounted && course?.current_week !== null && course?.current_week !== undefined
      ? course.weeks.find((w) => w.week_no === course.current_week) ?? null
      : null;

  return (
    <div className="rounded-2xl border border-black/5 bg-white p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-black/70">{copy.courseProgressTitle}</h2>
        {mounted && <span className="text-xs text-black/45">{course?.course_title}</span>}
      </div>

      {!loaded && <p className="mt-3 text-sm text-black/50">{copy.loading}</p>}

      {loaded && error && (
        <div className="mt-3">
          <p className="text-sm text-red-600">{error}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="mt-2 text-sm text-black/60 underline"
          >
            {copy.retry}
          </button>
        </div>
      )}

      {loaded && !error && !mounted && (
        <p className="mt-3 text-sm text-black/50">{copy.courseProgressNoCourse}</p>
      )}

      {loaded && !error && mounted && course && (
        <>
          {/* 大字：Week X / 8 — the number is the server's current_week. */}
          <div className="mt-3 flex flex-wrap items-end gap-4">
            <p className="text-3xl font-semibold tracking-tight text-[#00023D]">
              {copy.courseProgressWeekPrefix}
              {course.current_week}
              {copy.courseProgressWeekSuffix}
            </p>
            <p className="pb-1 text-sm text-black/60">
              {copy.courseProgressClassMastery}:{' '}
              <span className="font-medium text-[#00023D]">
                {pctText(currentRow?.mastery_pct ?? null)}
              </span>
            </p>
          </div>

          {/* 8 rows: title + status all come from the server; the card renders. */}
          <div className="mt-4 space-y-1.5">
            {course.weeks.map((w) => (
              <div
                key={w.week_no}
                className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-xs ${
                  w.status === 'active' ? 'bg-[#00023D]/5' : 'bg-black/[0.02]'
                }`}
              >
                <span className="w-14 shrink-0 text-black/50">
                  {copy.courseProgressWeekPrefix}
                  {w.week_no}
                </span>
                <span className="min-w-0 flex-1 truncate text-black/70">{w.title}</span>
                <span className="shrink-0 text-black/45">{pctText(w.mastery_pct)}</span>
                <span className="w-20 shrink-0 text-right text-black/60">{statusLabel(w.status)}</span>
              </div>
            ))}
          </div>

          <p className="mt-2 text-xs text-black/40">{copy.weekMapLegend}</p>

          {note && <p className="mt-3 text-xs text-black/60">{note}</p>}

          <div className="mt-4 flex justify-end">
            {course.state === 'completed' ? (
              <span className="rounded-lg bg-black/5 px-4 py-2 text-sm text-black/60">
                {copy.courseProgressCompleted}
              </span>
            ) : (
              <button
                type="button"
                disabled={busy}
                onClick={advance}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {busy ? copy.courseProgressAdvancing : copy.courseProgressNextWeek}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
