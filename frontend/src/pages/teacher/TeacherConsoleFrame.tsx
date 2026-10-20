// PR-5 — shared chrome for the teacher report console (/teacher/*).
//
// One frame so the five A-pages share guard + nav + heading styles. Children
// mount only once the guard is `ready`, so no page fires a /api/teacher/* call
// for a non-teacher session.

import type { ReactNode } from 'react';
import { Navigate, NavLink, useNavigate } from 'react-router';
import { copyEn as copy } from '../../lib/i18n';
import { AppShell } from '../../components/AppShell';
import { useTeacherGuard } from '../../hooks/useTeacherGuard';

const NAV: { to: string; label: string; testId: string }[] = [
  { to: '/teacher/scores', label: 'Weekly scores', testId: 'nav-scores' },
  { to: '/teacher/generate', label: 'Generate draft', testId: 'nav-generate' },
  { to: '/teacher/reports', label: 'Reports', testId: 'nav-reports' },
  { to: '/teacher/crosswalk', label: 'Crosswalk', testId: 'nav-crosswalk' },
];

interface TeacherConsoleFrameProps {
  title: string;
  subtitle: string;
  children: ReactNode;
}

export function TeacherConsoleFrame({ title, subtitle, children }: TeacherConsoleFrameProps) {
  const guard = useTeacherGuard();
  const navigate = useNavigate();

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

  return (
    <AppShell user={guard.user}>
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">{title}</h1>
          <p className="mt-0.5 text-xs text-black/40">{subtitle}</p>
        </div>

        <nav
          className="flex w-fit flex-wrap gap-1 rounded-full bg-white p-1 shadow-sm ring-1 ring-black/5"
          aria-label="Teacher report console"
        >
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              data-testid={item.testId}
              className={({ isActive }) =>
                `rounded-full px-4 py-1.5 text-sm font-bold transition-colors ${
                  isActive ? 'bg-[#00023D] text-white' : 'text-black/45 hover:text-[#00023D]'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {children}
      </div>
    </AppShell>
  );
}
