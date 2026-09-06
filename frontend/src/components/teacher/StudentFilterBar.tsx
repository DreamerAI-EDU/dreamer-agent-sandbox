// W3-B 步骤 3 — Client-side filter bar (Class Lens roster).
//
// Three independent local filters over the loaded roster (instruction §7).
// No backend pagination needed at class scale. All options are labelled for
// the English teacher console.

import type { TeacherClassStudent } from '../../lib/teacherTypes';

export type MasteryFilter = 'all' | 'low' | 'mid' | 'high' | 'none';
export type ConsentFilter = 'all' | 'agreed' | 'unsigned' | 'withdrawn';

export interface StudentFilters {
  ageBand: string; // '' = all
  mastery: MasteryFilter;
  consent: ConsentFilter;
}

export const DEFAULT_FILTERS: StudentFilters = {
  ageBand: '',
  mastery: 'all',
  consent: 'all',
};

interface StudentFilterBarProps {
  filters: StudentFilters;
  onChange: (next: StudentFilters) => void;
  availableAgeBands: string[];
}

const MASTERY_OPTIONS: { value: MasteryFilter; label: string }[] = [
  { value: 'all', label: 'All mastery' },
  { value: 'low', label: '< 50%' },
  { value: 'mid', label: '50–75%' },
  { value: 'high', label: '> 75%' },
  { value: 'none', label: 'No data' },
];

const CONSENT_OPTIONS: { value: ConsentFilter; label: string }[] = [
  { value: 'all', label: 'All consent' },
  { value: 'agreed', label: 'Agreed' },
  { value: 'unsigned', label: 'Unsigned' },
  { value: 'withdrawn', label: 'Withdrawn' },
];

const AGE_LABELS: Record<string, string> = {
  'P1-P3': 'P1–P3',
  'P4-P6': 'P4–P6',
  'S1-S3': 'S1–S3',
};

export function StudentFilterBar({
  filters,
  onChange,
  availableAgeBands,
}: StudentFilterBarProps) {
  const update = (patch: Partial<StudentFilters>) => onChange({ ...filters, ...patch });

  const selectCls =
    'h-9 rounded-lg border border-black/10 bg-white px-2.5 text-sm text-black/70 focus:border-[#00023D] focus:outline-none';

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select
        aria-label="Age band"
        className={selectCls}
        value={filters.ageBand}
        onChange={(e) => update({ ageBand: e.target.value })}
      >
        <option value="">All age bands</option>
        {availableAgeBands.map((band) => (
          <option key={band} value={band}>
            {AGE_LABELS[band] ?? band}
          </option>
        ))}
      </select>

      <select
        aria-label="Mastery range"
        className={selectCls}
        value={filters.mastery}
        onChange={(e) => update({ mastery: e.target.value as MasteryFilter })}
      >
        {MASTERY_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      <select
        aria-label="Consent"
        className={selectCls}
        value={filters.consent}
        onChange={(e) => update({ consent: e.target.value as ConsentFilter })}
      >
        {CONSENT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>

      {(filters.ageBand !== '' || filters.mastery !== 'all' || filters.consent !== 'all') && (
        <button
          type="button"
          onClick={() => onChange({ ...DEFAULT_FILTERS })}
          className="rounded-lg px-2.5 py-1.5 text-xs text-black/50 underline-offset-2 hover:text-[#00023D] hover:underline"
        >
          Clear
        </button>
      )}
    </div>
  );
}

/** Pure local filtering — applied in ClassLensView. */
export function applyFilters(
  students: TeacherClassStudent[],
  filters: StudentFilters,
): TeacherClassStudent[] {
  return students.filter((s) => {
    if (filters.ageBand && s.age_band !== filters.ageBand) return false;
    const m = s.mastery_pct; // raw 0..1
    switch (filters.mastery) {
      case 'low':
        if (m === null || m >= 0.5) return false;
        break;
      case 'mid':
        if (m === null || m < 0.5 || m > 0.75) return false;
        break;
      case 'high':
        if (m === null || m <= 0.75) return false;
        break;
      case 'none':
        if (m !== null) return false;
        break;
      case 'all':
        break;
    }
    if (filters.consent !== 'all' && s.media_consent !== filters.consent) return false;
    return true;
  });
}
