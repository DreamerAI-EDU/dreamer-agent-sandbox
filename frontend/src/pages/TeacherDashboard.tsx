// W3-B 步骤 3 — Teacher Progress Lens (teacher console container).
//
// /teacher single route, view switched by query state (instruction §1) —
// mirrors the Parent Dashboard deep-link pattern:
//   /teacher                              → Class List (W3-C behaviour kept)
//   /teacher?class=<classId>              → Class Lens (progress overview)
//   /teacher?class=<classId>&student=<maskId>[&period=<p>] → Student Detail
//
// No extra path routes are registered (keeps Caddy try_files happy). The
// student identifier on the URL is ALWAYS the 8-char mask — the full uuid
// exists only inside the teacher-console API responses and is never
// rendered or linked.
//
// Guard mirrors the old TeacherHomePage (role check + 401 redirect). The
// W3-C landing was migrated into components/teacher/ClassListView.tsx; this
// page only dispatches between the three views.

import { useEffect, useState } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router';
import { api, ApiError } from '../lib/api';
import { copyEn as copy } from '../lib/i18n';
import { AppShell } from '../components/AppShell';
import { ClassListView } from '../components/teacher/ClassListView';
import { ClassLensView } from '../components/teacher/ClassLensView';
import { TeacherStudentDetail } from '../components/teacher/TeacherStudentDetail';
import { teacherMaskOf } from '../lib/teacherTypes';
import type { ParentPeriod } from '../lib/parentTypes';
import type { User } from '../lib/types';

type GuardState =
  | { kind: 'loading' }
  | { kind: 'redirect'; to: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; user: User };

function isParentPeriod(v: string | null): v is ParentPeriod {
  return v === 'weekly' || v === 'cycle' || v === 'journey';
}

export function TeacherDashboard() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [guard, setGuard] = useState<GuardState>({ kind: 'loading' });

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
          setGuard({
            kind: 'error',
            message: err instanceof ApiError ? err.message : copy.unexpectedError,
          });
        }
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // ---- query-state routing -------------------------------------------
  const classId = searchParams.get('class') ?? '';
  const rawStudent = searchParams.get('student') ?? '';
  // Defensive: tolerate a pasted full uuid by trimming to the 8-char mask.
  const studentMask = teacherMaskOf(rawStudent);
  const period: ParentPeriod = isParentPeriod(searchParams.get('period'))
    ? (searchParams.get('period') as ParentPeriod)
    : 'cycle';

  const patchQuery = (patch: (next: URLSearchParams) => void, replace = false) => {
    const next = new URLSearchParams(searchParams);
    patch(next);
    setSearchParams(next, { replace });
  };

  const openClass = (id: string) =>
    patchQuery((next) => {
      next.set('class', id);
      next.delete('student');
      next.delete('period');
    });
  const backToClasses = () =>
    patchQuery((next) => {
      next.delete('class');
      next.delete('student');
      next.delete('period');
    });
  const openStudent = (mask: string) =>
    patchQuery((next) => {
      next.set('student', mask);
      next.delete('period');
    });
  const backToClass = () =>
    patchQuery((next) => {
      next.delete('student');
      next.delete('period');
    });
  const changePeriod = (p: ParentPeriod) => patchQuery((next) => next.set('period', p));

  // ---- rendering -------------------------------------------------------
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
            className="mt-4 rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-[#00023D]/15"
          >
            {copy.loginBtn}
          </button>
        </div>
      </div>
    );
  }

  const showDetail = Boolean(classId && studentMask);
  const showLens = Boolean(classId) && !studentMask;

  return (
    <AppShell user={guard.user}>
      {showDetail ? (
        <TeacherStudentDetail
          key={`${classId}:${studentMask}:${period}`}
          studentMask={studentMask}
          period={period}
          onPeriodChange={changePeriod}
          onBackToClass={backToClass}
        />
      ) : showLens ? (
        <ClassLensView
          key={classId}
          classId={classId}
          onBack={backToClasses}
          onOpenStudent={openStudent}
        />
      ) : (
        <ClassListView onOpenClass={openClass} />
      )}
    </AppShell>
  );
}
