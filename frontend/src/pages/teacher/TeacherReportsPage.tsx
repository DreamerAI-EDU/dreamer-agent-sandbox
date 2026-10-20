// PR-5 A3 — report list with status filter (GET /api/teacher/reports).
//
// The status filter is a server-side query parameter (`?status=`), 422 on an
// unknown value — the chips therefore map 1:1 onto REPORT_STATUSES. `counts`
// in the same response feeds the chip badges, so no second round-trip.
//
// Student names are resolved from the roster (report rows only carry the raw
// student_id); display always goes through mask().

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../../lib/api';
import type { ReportRow, ReportStatus } from '../../lib/reportTypes';
import { TeacherConsoleFrame } from './TeacherConsoleFrame';
import { mask, useTeacherRoster } from '../../hooks/useTeacherRoster';

const STATUS_LABEL: Record<ReportStatus, string> = {
  pending_review: '待審',
  approved: '已批核',
  rejected: '已駁回',
  superseded: '已被取代',
};

const FILTERS: (ReportStatus | '')[] = ['', 'pending_review', 'approved', 'rejected', 'superseded'];

export function TeacherReportsPage() {
  const roster = useTeacherRoster();
  const [status, setStatus] = useState<ReportStatus | ''>('');
  const [rows, setRows] = useState<ReportRow[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const nameOf = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of roster.students) map.set(s.student_id, s.display_name);
    return map;
  }, [roster.students]);

  const load = useCallback(async (next: ReportStatus | '') => {
    setLoading(true);
    setError('');
    try {
      const resp = await api.teacherReports(next || undefined);
      setRows(resp.reports);
      setCounts(resp.counts as unknown as Record<string, number>);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : '載入失敗');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(status);
  }, [load, status]);

  const chipClass = (active: boolean) =>
    `rounded-full px-3 py-1.5 text-xs font-bold transition-colors ${
      active ? 'bg-[#00023D] text-white' : 'bg-black/5 text-black/50 hover:bg-[#00023D]/15'
    }`;

  return (
    <TeacherConsoleFrame
      title="報告列表"
      subtitle="按狀態過濾；待審報告可進入審閱修改"
    >
      <div className="flex flex-wrap gap-2" data-testid="reports-filters">
        {FILTERS.map((f) => {
          const label = f === '' ? '全部' : STATUS_LABEL[f];
          const badge = f === '' ? undefined : counts[f];
          return (
            <button
              key={f || 'all'}
              type="button"
              onClick={() => setStatus(f)}
              className={chipClass(status === f)}
              data-testid={`reports-filter-${f || 'all'}`}
            >
              {label}
              {badge !== undefined ? `（${badge}）` : ''}
            </button>
          );
        })}
        <button
          type="button"
          onClick={() => void load(status)}
          className="rounded-full border border-black/10 px-3 py-1.5 text-xs font-bold text-black/50 hover:bg-[#00023D]/10"
        >
          重新載入
        </button>
      </div>

      {loading && <p className="text-sm text-black/40">載入報告…</p>}
      {error && <p className="text-sm text-red-600">{error}</p>}

      {!loading && !error && rows.length === 0 && (
        <div className="rounded-2xl border border-black/5 bg-white p-6 text-sm text-black/40 shadow-sm">
          呢個狀態之下暫時未有報告。
        </div>
      )}

      {rows.length > 0 && (
        <div className="overflow-hidden rounded-2xl border border-black/5 bg-white shadow-sm">
          <table className="w-full text-left text-sm" data-testid="reports-table">
            <thead className="bg-black/[0.02] text-[11px] uppercase tracking-wide text-black/40">
              <tr>
                <th className="px-4 py-2 font-bold">學生</th>
                <th className="px-4 py-2 font-bold">週次</th>
                <th className="px-4 py-2 font-bold">語言</th>
                <th className="px-4 py-2 font-bold">狀態</th>
                <th className="px-4 py-2 font-bold">版本</th>
                <th className="px-4 py-2 font-bold">編輯</th>
                <th className="px-4 py-2 font-bold"> </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.report_id} className="border-t border-black/5">
                  <td className="px-4 py-2 text-[#00023D]">
                    {nameOf.get(r.student_id) ?? mask(r.student_id)}
                    <span className="ml-1 text-[11px] text-black/30">{mask(r.student_id)}</span>
                  </td>
                  <td className="px-4 py-2 text-black/60">
                    W{r.week_from}–W{r.week_to}
                  </td>
                  <td className="px-4 py-2 text-black/60">{r.lang_code}</td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-[11px] font-bold ${
                        r.status === 'pending_review'
                          ? 'bg-amber-100 text-amber-800'
                          : r.status === 'approved'
                            ? 'bg-emerald-100 text-emerald-800'
                            : r.status === 'rejected'
                              ? 'bg-red-100 text-red-700'
                              : 'bg-black/10 text-black/50'
                      }`}
                    >
                      {STATUS_LABEL[r.status]}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-black/60">v{r.version}</td>
                  <td className="px-4 py-2 text-black/60">{r.teacher_edits_count}</td>
                  <td className="px-4 py-2">
                    <Link
                      to={`/teacher/reports/${r.report_id}`}
                      className="font-bold text-[#00023D] underline-offset-2 hover:underline"
                    >
                      {r.status === 'pending_review' ? '審閱' : '查看'}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TeacherConsoleFrame>
  );
}
