// PR-5 B1 / B2 — parent-console guard for the report read-only views.
//
// Same discipline as ParentDashboard's bootstrap: /api/auth/me must say
// `parent` (teacher/admin go to /safety), and every required consent document
// must be agreed before a report body may be shown (else /consent). The
// backend re-checks ownership on every /api/parent/reports call — this gate
// only keeps the chrome off the wrong screen.

import { useEffect, useState } from 'react';
import { api, ApiError } from '../lib/api';
import { copyEn as copy } from '../lib/i18n';
import type { Student, User } from '../lib/types';

export type ParentGuardState =
  | { kind: 'loading' }
  | { kind: 'redirect'; to: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; user: User; students: Student[] };

export function useParentReportsGuard(): ParentGuardState {
  const [state, setState] = useState<ParentGuardState>({ kind: 'loading' });

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await api.me();
        if (!alive) return;
        if (me.user.role !== 'parent') {
          setState({
            kind: 'redirect',
            to: me.user.role === 'teacher' ? '/teacher/reports' : '/safety',
          });
          return;
        }
        const status = await api.consentStatus();
        if (!alive) return;
        const pending = Object.values(status.documents).find(
          (d) => d.required && d.status !== 'agreed',
        );
        if (pending) {
          setState({ kind: 'redirect', to: '/consent' });
          return;
        }
        const resp = await api.students();
        if (!alive) return;
        setState({ kind: 'ready', user: me.user, students: resp.students });
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          setState({ kind: 'redirect', to: '/login' });
        } else {
          setState({
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

  return state;
}
