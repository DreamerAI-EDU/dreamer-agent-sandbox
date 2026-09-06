// W3-B 步骤 3 — One confirmed student row inside the Class Lens.
//
// Columns (instruction §5 mapped to the REAL backend row shape):
//   display_name      → profile.first_name (B24 — never full name / id)
//   last_label_kid    → kid-facing softened label, verbatim (no translation)
//   mastery_pct       → raw 0..1 → MasteryBar (multiplies by 100 internally)
//   last_activity_at  → session/assessment last activity, relative English
//   media_consent     → ConsentIndicator three-state lamp
//   action            → "View" → deep link ?class=<id>&student=<mask>
// The 8-char mask is derived here; the full student uuid is never rendered.

import { ConsentIndicator } from '../parent/ConsentIndicator';
import { MasteryBar } from '../parent/MasteryBar';
import { masteryToPercent } from '../../lib/parentTypes';
import { fmtRelativeDay, teacherMaskOf } from '../../lib/teacherTypes';
import type { TeacherClassStudent } from '../../lib/teacherTypes';

interface StudentRowProps {
  student: TeacherClassStudent;
  /** Called with the 8-char mask when the teacher opens the detail. */
  onView: (maskId: string) => void;
}

const AGE_BAND_LABELS: Record<string, string> = {
  'P1-P3': 'P1–P3',
  'P4-P6': 'P4–P6',
  'S1-S3': 'S1–S3',
};

export function StudentRow({ student, onView }: StudentRowProps) {
  const pct = masteryToPercent(student.mastery_pct);
  const maskId = teacherMaskOf(student.student_id);

  return (
    <div className="rounded-2xl border border-black/5 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
        {/* identity */}
        <div className="min-w-[150px] flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-black/85">{student.display_name}</span>
            {student.age_band && (
              <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/50">
                {AGE_BAND_LABELS[student.age_band] ?? student.age_band}
              </span>
            )}
          </div>
          <p className="mt-0.5 text-xs text-black/40">
            Latest label:{' '}
            <span className="text-black/70">{student.last_label_kid || '—'}</span>
          </p>
        </div>

        {/* mastery */}
        <div className="w-full min-w-[200px] flex-1 sm:w-56">
          <MasteryBar
            mastery={student.mastery_pct}
            title="Mastery"
            label={pct === null ? 'no data' : `${pct}%`}
          />
        </div>

        {/* last activity */}
        <div className="text-xs text-black/50">
          <span className="block text-black/35">Last session</span>
          <span className="text-black/70">{fmtRelativeDay(student.last_activity_at)}</span>
        </div>

        {/* consent lamp */}
        <ConsentIndicator status={student.media_consent} label="Media" />

        {/* action */}
        <button
          type="button"
          onClick={() => onView(maskId)}
          className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          View
        </button>
      </div>
    </div>
  );
}
