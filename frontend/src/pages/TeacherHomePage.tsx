// W3-C — minimal read-only Teacher Home (/teacher).
// Boundary (spec §3.1, enforced): NO action buttons — confirm stays on the
// existing path; no class/student management; no booking/scheduling UI.
// Class-type grouping (monthly vs workshop) + age chips + 1-on-1 badge follow
// the boss ruling (2026-09-04): classes gained class_type / grade_band /
// is_one_on_one columns via one idempotent migration; this page renders the
// new fields. Teacher-facing UI is pinned to English (copyEn) — the register
// flow and console target overseas schools first.

import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { copyEn as copy } from '../lib/i18n';
import { AppShell } from '../components/AppShell';
import type { ClassSummary, PendingStudent, User } from '../lib/types';

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

type GuardState =
  | { kind: 'loading' }
  | { kind: 'redirect'; to: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; user: User };

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

export function TeacherHomePage() {
  const navigate = useNavigate();

  const [guard, setGuard] = useState<GuardState>({ kind: 'loading' });
  const [classes, setClasses] = useState<ClassWithPending[] | null>(null);
  const [loadError, setLoadError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await api.me();
        if (!alive) return;
        const u = me.user;
        if (u.role !== 'teacher') {
          setGuard({ kind: 'redirect', to: u.role === 'parent' ? '/home' : '/safety' });
          return;
        }
        setGuard({ kind: 'ready', user: u });
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          setGuard({ kind: 'redirect', to: '/login' });
        } else {
          setGuard({ kind: 'error', message: err instanceof ApiError ? err.message : copy.unexpectedError });
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, [copy.unexpectedError]);

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
      // Pending lists load in parallel; a failure on one class does not
      // block the landing page (counts come from the list response).
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
    if (guard.kind === 'ready' && classes === null && !busy) {
      void loadClasses();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guard.kind, classes === null]);

  if (guard.kind === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }
  if (guard.kind === 'redirect') return <Navigate to={guard.to} replace />;
  if (guard.kind === 'error') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{guard.message}</p>
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="mt-4 rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
          >
            {copy.loginBtn}
          </button>
        </div>
      </div>
    );
  }

  return (
    <AppShell user={guard.user}>
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

                    {c.pendingLoaded && c.pendingStudents.length > 0 && (
                      <div className="mt-4 border-t border-black/5 pt-3">
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
                      </div>
                    )}
                    {c.pendingLoaded && c.pendingStudents.length === 0 && (
                      <p className="mt-3 text-xs text-black/35">{copy.noPendingStudents}</p>
                    )}
                  </div>
                ))}
              </section>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}
