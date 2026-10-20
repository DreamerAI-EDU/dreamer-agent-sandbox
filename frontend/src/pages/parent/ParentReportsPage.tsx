// PR-5 B1 — approved-report list for a parent (GET /api/parent/reports).
//
// Rules enforced here (design book §4.3 / 施工令 §一 B1–B5):
//   * only `approved` rows are ever reachable — the backend filters in SQL;
//   * the child is picked from /api/students (8-char mask ids) and put in the
//     URL so B2 can resolve the same child;
//   * the stage is ALWAYS the frozen §三 friendly name (bandLabel) — the raw
//     band code is never rendered (§B3);
//   * no editing UI, no PDF button (PR-6), no descriptor text of our own.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, Navigate, useSearchParams } from 'react-router';
import { api, ApiError } from '../../lib/api';
import { PARENT_REPORT_COPY, bandLabel, toReportLang } from '../../lib/parentReportCopy';
import { AppShell } from '../../components/AppShell';
import { useParentReportsGuard } from '../../hooks/useParentReportsGuard';
import type { ParentReportRow } from '../../lib/reportTypes';

export function ParentReportsPage() {
  const guard = useParentReportsGuard();
  const [params, setParams] = useSearchParams();
  const [rows, setRows] = useState<ParentReportRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const students = useMemo(
    () => (guard.kind === 'ready' ? guard.students : []),
    [guard],
  );
  const childId = useMemo(() => {
    const raw = (params.get('student') ?? '').trim();
    if (raw) return raw;
    return students[0]?.id ?? '';
  }, [params, students]);

  // The report language decides which frozen copy set the chrome uses.
  const lang = useMemo(
    () => toReportLang(rows[0]?.lang_code ?? students[0]?.lang_code),
    [rows, students],
  );
  const copy = PARENT_REPORT_COPY[lang];

  const load = useCallback(async (studentId: string) => {
    setLoading(true);
    setError('');
    try {
      const resp = await api.parentReportList(studentId);
      setRows(resp.reports);
    } catch (err) {
      setRows([]);
      setError(err instanceof ApiError ? err.message : PARENT_REPORT_COPY.en.notFound);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!childId) return;
    void load(childId);
  }, [childId, load]);

  useEffect(() => {
    if (childId && params.get('student') !== childId) {
      const next = new URLSearchParams(params);
      next.set('student', childId);
      setParams(next, { replace: true });
    }
  }, [childId, params, setParams]);

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
        <p className="text-sm text-red-600">{guard.message}</p>
      </div>
    );
  }

  return (
    <AppShell user={guard.user}>
      <div className="space-y-5">
        <div>
          <h1 className="text-xl font-semibold tracking-tight text-[#00023D]">{copy.title}</h1>
          <p className="mt-0.5 text-xs text-black/40">{copy.subtitle}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {students.length > 1 && (
            <div className="flex gap-1 rounded-full bg-white p-1 shadow-sm ring-1 ring-black/5">
              {students.map((s) => {
                const active = s.id === childId;
                return (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => {
                      const next = new URLSearchParams(params);
                      next.set('student', s.id);
                      setParams(next, { replace: true });
                    }}
                    className={`rounded-full px-3 py-1.5 text-xs font-bold transition-colors ${
                      active ? 'bg-[#00023D] text-white' : 'text-black/45'
                    }`}
                    data-testid={`parent-child-${s.id}`}
                  >
                    {s.first_name}
                  </button>
                );
              })}
            </div>
          )}
          <Link
            to="/parent"
            className="rounded-full border border-black/10 bg-white px-3 py-1.5 text-xs font-bold text-black/50 hover:bg-[#00023D]/10"
          >
            ← 學習主頁
          </Link>
        </div>

        <h2 className="text-sm font-bold text-[#00023D]">{copy.listTitle}</h2>

        {loading && <p className="text-sm text-black/40">{copy.loading}</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && rows.length === 0 && (
          <div className="rounded-2xl border border-black/5 bg-white p-6 text-sm text-black/40 shadow-sm">
            {copy.empty}
          </div>
        )}

        {rows.length > 0 && (
          <ul className="space-y-2" data-testid="parent-report-list">
            {rows.map((r) => {
              const rowLang = toReportLang(r.lang_code);
              const rowCopy = PARENT_REPORT_COPY[rowLang];
              return (
                <li
                  key={r.report_id}
                  className="rounded-2xl border border-black/5 bg-white p-4 shadow-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-bold text-[#00023D]">
                        {rowCopy.weekRange} {r.week_from}–{r.week_to} · {r.published_at.slice(0, 10)}
                      </p>
                      <p className="mt-1 text-[11px] text-black/40">
                        {rowCopy.band} {bandLabel(r.age_band, rowLang)} · {r.lang_code} · 
                        {rowCopy.version} v{r.version}
                      </p>
                    </div>
                    <Link
                      to={`/parent/reports/${r.report_id}?student=${encodeURIComponent(r.student_id)}`}
                      className="rounded-full bg-[#00023D] px-4 py-1.5 text-xs font-bold text-white"
                      data-testid={`parent-open-${r.report_id}`}
                    >
                      {rowCopy.openReport}
                    </Link>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </AppShell>
  );
}
