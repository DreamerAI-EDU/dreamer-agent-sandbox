// PR-5 — teacher-console session guard (same shape as TeacherDashboard's).
//
// /teacher/* pages are teacher-only (§A6 "仅老师角色可见"; the backend already
// answers 401/403 on every /api/teacher/* route — this gate only keeps the
// chrome and the crosswalk page off non-teacher screens).

import { useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { copyEn as copy } from '../lib/i18n';
import type { User } from '../lib/types';

export type TeacherGuardState =
  | { kind: 'loading' }
  | { kind: 'redirect'; to: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; user: User };

export function useTeacherGuard(): TeacherGuardState {
  const [guard, setGuard] = useState<TeacherGuardState>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await api.me();
        if (!alive) return;
        const u = me.user;
        if (u.role !== 'teacher') {
          setGuard({
            kind: 'redirect',
            to: u.role === 'parent' ? '/parent' : '/safety',
          });
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

  return guard;
}
