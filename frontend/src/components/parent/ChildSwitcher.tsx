// W3-B — Child switcher.
//
// Renders the parent's children (from /api/students; the backend auth/me
// payload has no `children` array — students[0] plays the instruction's
// "children[0]" default-route role) as pills. Selection is lifted to
// ParentDashboard which syncs the deep link ?student=<mask>.

import type { Student } from '../../lib/types';

interface ChildSwitcherProps {
  students: Student[];
  selectedId: string | null;
  onChange: (studentId: string) => void;
}

export function ChildSwitcher({ students, selectedId, onChange }: ChildSwitcherProps) {
  if (students.length === 0) {
    return (
      <div className="rounded-2xl border border-black/5 bg-white px-4 py-6 text-center text-sm text-black/50">
        帳號暫時未有小朋友。
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs uppercase tracking-wide text-black/40">Children</span>
      {students.map((s) => {
        const active = s.id === selectedId;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onChange(s.id)}
            className={`rounded-full border px-3.5 py-1.5 text-sm transition-colors ${
              active
                ? 'border-[#00023D] bg-[#00023D] text-white'
                : 'border-black/10 bg-white text-black/70 hover:border-black/20 hover:bg-[#00023D]/15'
            }`}
          >
            {s.first_name}
          </button>
        );
      })}
    </div>
  );
}
