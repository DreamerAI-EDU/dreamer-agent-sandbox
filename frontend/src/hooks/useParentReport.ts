// W3-B — Parent report data hook.
//
// Wraps GET /api/parent/report?student_id=<mask>&period=<weekly|cycle|journey>
// (envelope shape from lib/parentTypes.ts) and exposes the classic
// loading / error / data trio. The caller is ParentDashboard.tsx, which owns
// studentId + period in global state and deep-links them via URL
// (?student=<uuid>&period=...).

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { ParentPeriod, ParentReportEnvelope } from '../lib/parentTypes';

export interface UseParentReportResult {
  loading: boolean;
  error: string;
  data: ParentReportEnvelope | null;
  reload: () => void;
}

/**
 * Fetch the parent report for one student over one period.
 * - studentId: 8-char mask prefix (never the full uuid).
 * - period:    weekly | cycle | journey.
 * Pass studentId = null to idle (e.g. no child selected yet) — no request.
 */
export function useParentReport(
  studentId: string | null,
  period: ParentPeriod,
): UseParentReportResult {
  const [data, setData] = useState<ParentReportEnvelope | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);

  // Stale-response guard: only the latest request may write state.
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    if (!studentId) {
      setData(null);
      setError('');
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    setError('');
    try {
      const envelope = await api.parentReport(studentId, period);
      if (seq !== requestSeq.current) return; // superseded by a newer request
      setData(envelope);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setData(null);
      setError(err instanceof ApiError ? err.message : '載入報告時發生錯誤');
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [studentId, period]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback(() => {
    setTick((t) => t + 1);
  }, []);

  useEffect(() => {
    if (tick === 0) return;
    void load();
  }, [tick, load]);

  return { loading, error, data, reload };
}
