// W3-B 步骤 3 — Class Lens main view (Teacher Progress Lens body).
//
// Rendered by TeacherDashboard when ?class=<classId> is present (no
// ?student). Data source: GET /api/teacher/classes/{classId}/progress via
// useTeacherClassProgress. Owns the roster local filters (StudentFilterBar +
// applyFilters) and hands "View" clicks up to the page as 8-char masks.
//
// Roster rows carry full student uuids from the teacher console surface;
// only 8-char masks ever travel to the URL / parent components.

import { useMemo, useState } from 'react';
import { useTeacherClassProgress } from '../../hooks/useTeacherProgress';
import { masteryToPercent } from '../../lib/parentTypes';
import { ClassStatsCard } from './ClassStatsCard';
import { CourseProgressCard } from './CourseProgressCard';
import { InviteStudentDialog } from './InviteStudentDialog';
import { StudentRow } from './StudentRow';
import { StudentFilterBar, DEFAULT_FILTERS, applyFilters } from './StudentFilterBar';
import type { StudentFilters } from './StudentFilterBar';
import { copyEn as copy } from '../../lib/i18n';

interface ClassLensViewProps {
  classId: string;
  onBack: () => void;
  /** Called with the 8-char student mask. */
  onOpenStudent: (maskId: string) => void;
}

const AGE_LABELS: Record<string, string> = {
  'P1-P3': 'P1–P3',
  'P4-P6': 'P4–P6',
  'S1-S3': 'S1–S3',
};

export function ClassLensView({ classId, onBack, onOpenStudent }: ClassLensViewProps) {
  const { loading, error, data, reload } = useTeacherClassProgress(classId);
  const [filters, setFilters] = useState<StudentFilters>(DEFAULT_FILTERS);
  // Bridge-3c 掣 3: the invite entry lives in this view's header.
  const [inviteOpen, setInviteOpen] = useState(false);

  const availableAgeBands = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    for (const s of data.students) {
      if (s.age_band) seen.add(s.age_band);
    }
    // Stable order: prefer the P1-P3/P4-P6/S1-S3 vocabulary, then extras.
    const preferred = ['P1-P3', 'P4-P6', 'S1-S3'];
    return [...preferred.filter((b) => seen.has(b)), ...[...seen].filter((b) => !preferred.includes(b))];
  }, [data]);

  const filtered = useMemo(
    () => (data ? applyFilters(data.students, filters) : []),
    [data, filters],
  );

  const avgPct = masteryToPercent(data?.stats.average_mastery_pct ?? null);

  return (
    <div className="space-y-5">
      {/* back + class identity */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-lg border border-black/10 bg-white px-3 py-1.5 text-sm text-black/60 transition-colors hover:bg-[#00023D]/15"
        >
          ← Classes
        </button>

        {data && (
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">{data.class.name}</h1>
            {data.class.grade_band && (
              <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                {AGE_LABELS[data.class.grade_band] ?? data.class.grade_band}
              </span>
            )}
            {data.class.is_one_on_one && (
              <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                {copy.oneOnOneBadge}
              </span>
            )}
            <button
              type="button"
              onClick={() => setInviteOpen(true)}
              className="rounded-lg border border-black/10 bg-white px-3 py-1.5 text-sm font-medium text-black/70 transition-colors hover:bg-black/5"
            >
              {copy.inviteStudentBtn}
            </button>
          </div>
        )}
      </div>

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

      {/* 掣 4 — Week X/8 leads the view (decision ④); the card owns its own
          GET /api/classes/{id}/curriculum read, so a roster hiccup never
          hides the progress state. */}
      <CourseProgressCard classId={classId} onAdvanced={reload} />

      {data && (
        <>
          {/* stats */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <ClassStatsCard label="Students" value={String(data.stats.student_count)} hint="confirmed in this class" />
            <ClassStatsCard
              label="Average mastery"
              value={avgPct === null ? '—' : `${avgPct}%`}
              hint={avgPct === null ? 'no snapshot data yet' : 'latest snapshot average'}
              emphasize
            />
            <ClassStatsCard label="Pending" value={String(data.stats.pending_count)} hint="awaiting confirmation" />
          </div>

          {/* roster */}
          <div className="space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-black/70">Students</h2>
              <StudentFilterBar
                filters={filters}
                onChange={setFilters}
                availableAgeBands={availableAgeBands}
              />
            </div>

            {data.students.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-white/60 p-8 text-center text-sm text-black/50">
                No confirmed students in this class yet.
              </div>
            ) : filtered.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-black/10 bg-white/60 p-8 text-center text-sm text-black/50">
                No students match the current filters.
              </div>
            ) : (
              <div className="space-y-2.5">
                {filtered.map((s) => (
                  <StudentRow key={s.student_id} student={s} onView={onOpenStudent} />
                ))}
              </div>
            )}
          </div>
        </>
      )}

      {inviteOpen && (
        <InviteStudentDialog
          classId={classId}
          onClose={() => setInviteOpen(false)}
          // The roster/pending counts move once the invite lands; re-read the
          // route that owns them (same discipline as 掣 4's re-read).
          onInvited={reload}
        />
      )}
    </div>
  );
}
