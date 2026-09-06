// W3-B — Parent Dashboard main container (single /parent route entry).
//
// Layout of the three-layer UI tree:
//   ParentDashboard (page)                     ← global state owner
//   ├─ ChildSwitcher                           ← children from /api/students
//   ├─ PeriodTabs (weekly / cycle / journey)
//   └─ useParentReport(studentId, period)      ← GET /api/parent/report
//        ├─ FirstStepsView   (variant=first_steps)
//        ├─ WeeklyDigest     (period=weekly)
//        ├─ CycleReport      (period=cycle)
//        └─ JourneyView      (period=journey)
//
// Global state: studentId / period / report (three-state held here).
// Deep-link sync: URL ?student=<mask-uuid>&period=weekly|cycle|journey is
// read on mount and rewritten (history.replaceState) on every change.
//
// Default child = students[0] (the instruction says /api/auth/me returns
// children[0]; the real backend's me() has no children array, so students[0]
// from /api/students plays that role — see report §4).

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import type { Student, User } from '../lib/types';
import { PARENT_PERIODS } from '../lib/parentTypes';
import type { ParentPeriod } from '../lib/parentTypes';
import { AppShell } from '../components/AppShell';
import { ChildSwitcher } from '../components/parent/ChildSwitcher';
import { PeriodTabs } from '../components/parent/PeriodTabs';
import { WeeklyDigest } from '../components/parent/WeeklyDigest';
import { CycleReport } from '../components/parent/CycleReport';
import { JourneyView } from '../components/parent/JourneyView';
import { FirstStepsView } from '../components/parent/FirstStepsView';
import { useParentReport } from '../hooks/useParentReport';

/** Default tab — cycle report is the "8 週主報告". */
const DEFAULT_PERIOD: ParentPeriod = 'cycle';

function readUrlState(): { studentId: string | null; period: ParentPeriod } {
  const params = new URLSearchParams(window.location.search);
  const rawPeriod = params.get('period');
  const period = (PARENT_PERIODS as string[]).includes(rawPeriod ?? '')
    ? (rawPeriod as ParentPeriod)
    : DEFAULT_PERIOD;
  const rawStudent = params.get('student');
  return { studentId: rawStudent && rawStudent.trim() ? rawStudent.trim() : null, period };
}

function writeUrlState(studentId: string | null, period: ParentPeriod) {
  const params = new URLSearchParams(window.location.search);
  if (studentId) params.set('student', studentId);
  else params.delete('student');
  params.set('period', period);
  const qs = params.toString();
  window.history.replaceState(null, '', qs ? `${window.location.pathname}?${qs}` : window.location.pathname);
}

export function ParentDashboard() {
  const { copy } = useLang();
  const navigate = useNavigate();

  const initial = useMemo(() => readUrlState(), []);
  const [user, setUser] = useState<User | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [bootstrapError, setBootstrapError] = useState('');
  const [studentId, setStudentId] = useState<string | null>(initial.studentId);
  const [period, setPeriod] = useState<ParentPeriod>(initial.period);

  // ── Bootstrap: session + consent + children list ────────────────
  const load = useCallback(async () => {
    try {
      const me = await api.me();
      if (me.user.role === 'teacher' || me.user.role === 'admin') {
        navigate('/safety', { replace: true });
        return;
      }
      const status = await api.consentStatus();
      // Required docs must be agreed (status:'agreed'); backend vocabulary has
      // no boolean `agreed` key (auth/consent.py status_for_user).
      const pending = Object.values(status.documents).find(
        (d) => d.required && d.status !== 'agreed',
      );
      if (pending) {
        navigate('/consent', { replace: true });
        return;
      }
      setUser(me.user);
      const resp = await api.students();
      setStudents(resp.students);
      if (resp.students.length > 0) {
        // Default route child: keep a deep-linked student only if it exists.
        setStudentId((prev) =>
          prev && resp.students.some((s) => s.id === prev) ? prev : resp.students[0].id,
        );
      }
      setBootstrapError('');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate('/login', { replace: true });
        return;
      }
      setBootstrapError(err instanceof ApiError ? err.message : copy.unexpectedError);
    }
  }, [copy.unexpectedError, navigate]);

  useEffect(() => {
    // load() sets state only after await (async data fetch), never synchronously;
    // the react-hooks/set-state-in-effect guard is a false positive here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  // ── Deep-link sync: keep URL in step with global state ──────────
  useEffect(() => {
    writeUrlState(studentId, period);
  }, [studentId, period]);

  const report = useParentReport(studentId, period);

  const handleStudentChange = useCallback((id: string) => {
    setStudentId(id);
  }, []);

  const handlePeriodChange = useCallback((next: ParentPeriod) => {
    setPeriod(next);
  }, []);

  const handleRetry = useCallback(() => {
    void load();
    report.reload();
  }, [load, report]);

  // ── Loading / error shells ───────────────────────────────────────
  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{bootstrapError || copy.loading}</p>
      </div>
    );
  }

  const selectedStudent = students.find((s) => s.id === studentId) ?? null;

  return (
    <AppShell user={user}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">
              Parent Dashboard
            </h1>
            <p className="mt-0.5 text-xs text-black/40">
              小朋友嘅學習週報、週期報告與成長旅程
            </p>
          </div>
          {selectedStudent && (
            <span className="rounded-full border border-black/10 bg-white px-3 py-1 text-xs text-black/60">
              {selectedStudent.first_name} · {selectedStudent.age_band}
            </span>
          )}
        </div>

        {bootstrapError && (
          <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {bootstrapError}
            <button type="button" onClick={handleRetry} className="ml-3 underline">
              {copy.retry}
            </button>
          </div>
        )}

        <ChildSwitcher
          students={students}
          selectedId={studentId}
          onChange={handleStudentChange}
        />

        {!studentId && (
          <div className="rounded-2xl border border-black/5 bg-white px-5 py-10 text-center text-sm text-black/50">
            揀一位小朋友開始睇報告。
          </div>
        )}

        {studentId && (
          <>
            <PeriodTabs active={period} onChange={handlePeriodChange} />

            {report.loading && !report.data && (
              <div className="rounded-2xl border border-black/5 bg-white px-5 py-10 text-center text-sm text-black/50">
                {copy.loading}
              </div>
            )}

            {report.error && (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-8 text-center text-sm text-red-700">
                <p>{report.error}</p>
                <button type="button" onClick={handleRetry} className="mt-3 underline">
                  {copy.retry}
                </button>
              </div>
            )}

            {report.data && report.data.report.variant === 'first_steps' && (
              // variant=first_steps: baseline + roadmap only, no mastery
              // deep-dive (instruction 4.4) — shown regardless of the tab.
              <FirstStepsView
                digest={report.data.content}
                baseline={report.data.report.baseline}
                roadmap={report.data.report.roadmap}
                topics={report.data.report.topics}
              />
            )}

            {report.data && report.data.report.variant === 'standard' && period === 'weekly' && (
              <WeeklyDigest
                digest={report.data.content}
                period={report.data.report.period}
                summary={report.data.report.summary}
                topics={report.data.report.topics}
              />
            )}

            {report.data && report.data.report.variant === 'standard' && period === 'cycle' && (
              <CycleReport envelope={report.data} />
            )}

            {report.data && report.data.report.variant === 'standard' && period === 'journey' && (
              <JourneyView
                period={report.data.report.period}
                timeline={report.data.report.activity_timeline}
                topics={report.data.report.topics}
              />
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
