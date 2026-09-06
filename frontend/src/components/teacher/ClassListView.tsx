// W3-B 步骤 3 — Class List view (Teacher Progress Lens entry).
//
// Migrated verbatim from the W3-C landing page (previously inline in
// pages/TeacherHomePage.tsx) so that TeacherDashboard can switch views by
// query state. Behaviour and data flow are unchanged: /api/classes then
// parallel /api/classes/{id}/pending; a failing pending request never
// blocks the card.
//
// Teacher-facing UI is pinned to English (copyEn — the register flow and
// console target overseas schools first; same policy as W3-C).

import { useEffect, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { copyEn as copy } from '../../lib/i18n';
import type { ClassSummary, PendingStudent } from '../../lib/types';

interface ClassWithPending extends ClassSummary {
  pendingStudents: PendingStudent[];
  pendingLoaded: boolean;
}

type GroupKey = 'monthly' | 'workshop' | 'other';

interface ClassGroup {
  key: GroupKey;
  label: string;
  items: ClassWithPending[];
}

interface ClassListViewProps {
  /** Called with the class id when the teacher opens a class lens. */
  onOpenClass: (classId: string) => void;
}

function groupKeyOf(c: Pick<ClassSummary, 'class_type'>): GroupKey {
  return c.class_type === 'monthly' || c.class_type === 'workshop'
    ? c.class_type
    : 'other';
}

function buildGroups(classes: ClassWithPending[]): ClassGroup[] {
  const monthly: ClassWithPending[] = [];
  const workshop: ClassWithPending[] = [];
  const other: ClassWithPending[] = [];
  for (const c of classes) {
    (groupKeyOf(c) === 'monthly'
      ? monthly
      : groupKeyOf(c) === 'workshop'
        ? workshop
        : other
    ).push(c);
  }
  const groups: ClassGroup[] = [];
  if (monthly.length) groups.push({ key: 'monthly', label: copy.classGroupMonthly, items: monthly });
  if (workshop.length) groups.push({ key: 'workshop', label: copy.classGroupWorkshop, items: workshop });
  if (other.length) groups.push({ key: 'other', label: copy.classGroupOther, items: other });
  return groups;
}

export function ClassListView({ onOpenClass }: ClassListViewProps) {
  const [classes, setClasses] = useState<ClassWithPending[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);

  const loadClasses = async () => {
    setBusy(true);
    setLoadError('');
    try {
      const resp = await api.classes();
      const withPending: ClassWithPending[] = resp.classes.map((c) => ({
        ...c,
        pendingStudents: [],
        pendingLoaded: false,
      }));
      await Promise.all(
        withPending.map(async (c) => {
          try {
            const p = await api.classPending(c.id);
            c.pendingStudents = p.pending;
            c.pendingLoaded = true;
          } catch {
            c.pendingLoaded = true; // keep card usable, pending list hidden
          }
        }),
      );
      setClasses(withPending);
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!busy && classes === null) {
      void loadClasses();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classes === null]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{copy.teacherConsole}</h1>
        <p className="mt-1 text-sm text-black/50">{copy.teacherSideNote}</p>
      </div>

      {loadError && <p className="text-sm text-red-600">{loadError}</p>}

      {classes === null ? (
        <p className="text-sm text-black/50">{copy.loading}</p>
      ) : classes.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-black/10 bg-white/60 p-10 text-center">
          <p className="text-sm text-black/50">{copy.emptyClasses}</p>
        </div>
      ) : (
        <div className="space-y-8">
          {buildGroups(classes).map((g) => (
            <section key={g.key} className="space-y-3">
              <h2 className="text-sm font-medium text-black/60">{g.label}</h2>
              {g.items.map((c) => (
                <div
                  key={c.id}
                  className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm"
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-semibold tracking-tight">{c.name}</h3>
                    <span className="rounded-full bg-black/5 px-2 py-0.5 font-mono text-xs text-black/50">
                      {c.join_code}
                    </span>
                    {c.is_one_on_one === 1 && (
                      <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                        {copy.oneOnOneBadge}
                      </span>
                    )}
                    {c.grade_band && (
                      <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                        {copy.ageBands[c.grade_band] ?? c.grade_band}
                      </span>
                    )}
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                      {copy.confirmedLabel}: {c.confirmed_count}
                    </span>
                    <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/60">
                      {copy.pendingLabel}: {c.pending_count}
                    </span>
                  </div>

                  <div className="mt-4 border-t border-black/5 pt-3">
                    {c.pendingLoaded && c.pendingStudents.length > 0 && (
                      <>
                        <p className="text-xs font-medium text-black/50">{copy.pendingStudentsTitle}</p>
                        <ul className="mt-2 space-y-1.5">
                          {c.pendingStudents.map((s) => (
                            <li key={s.student_id} className="flex items-center gap-2 text-sm">
                              <span className="text-black/80">{s.first_name}</span>
                              <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/50">
                                {copy.ageBands[s.age_band] ?? s.age_band}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </>
                    )}
                    {c.pendingLoaded && c.pendingStudents.length === 0 && (
                      <p className="text-xs text-black/35">{copy.noPendingStudents}</p>
                    )}
                  </div>

                  <div className="mt-4 flex justify-end">
                    <button
                      type="button"
                      onClick={() => onOpenClass(c.id)}
                      className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
                    >
                      View progress
                    </button>
                  </div>
                </div>
              ))}
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
