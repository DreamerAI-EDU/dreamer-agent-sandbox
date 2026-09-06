// W3-B 步骤 3 — Teacher Progress data hooks.
//
// Wraps the two teacher-only progress endpoints (both GET, both carrying
// X-Requested-With via csrfOnGet:true like the parent report):
//   GET /api/teacher/classes/{classId}/progress
//   GET /api/teacher/student/{identifier}/progress?period=<weekly|cycle|journey>
//
// The identifier for the student endpoint accepts the FULL uuid or the
// 8-char mask prefix (backend resolve_student_identifier resolves both);
// this UI always passes the 8-char mask so full ids never touch the URL.
// Both hooks expose the classic loading / error / data / reload trio.

import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { ParentPeriod } from '../lib/parentTypes';
import type {
  TeacherClassProgressResponse,
  TeacherStudentProgressResponse,
} from '../lib/teacherTypes';

export interface UseTeacherClassProgressResult {
  loading: boolean;
  error: string;
  data: TeacherClassProgressResponse | null;
  reload: () => void;
}

/** Pass classId = null to idle (no request is fired). */
export function useTeacherClassProgress(
  classId: string | null,
): UseTeacherClassProgressResult {
  const [data, setData] = useState<TeacherClassProgressResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    if (!classId) {
      setData(null);
      setError('');
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    setError('');
    try {
      const resp = await api.teacherClassProgress(classId);
      if (seq !== requestSeq.current) return;
      setData(resp);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setData(null);
      setError(err instanceof ApiError ? err.message : 'Failed to load class progress');
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [classId]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (tick === 0) return;
    void load();
  }, [tick, load]);

  return { loading, error, data, reload };
}

export interface UseTeacherStudentProgressResult {
  loading: boolean;
  error: string;
  data: TeacherStudentProgressResponse | null;
  reload: () => void;
}

/** Pass identifier = null to idle. identifier is the 8-char mask prefix. */
export function useTeacherStudentProgress(
  identifier: string | null,
  period: ParentPeriod,
): UseTeacherStudentProgressResult {
  const [data, setData] = useState<TeacherStudentProgressResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tick, setTick] = useState(0);
  const requestSeq = useRef(0);

  const load = useCallback(async () => {
    if (!identifier) {
      setData(null);
      setError('');
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    setError('');
    try {
      const resp = await api.teacherStudentProgress(identifier, period);
      if (seq !== requestSeq.current) return;
      setData(resp);
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setData(null);
      setError(err instanceof ApiError ? err.message : 'Failed to load student progress');
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [identifier, period]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (tick === 0) return;
    void load();
  }, [tick, load]);

  return { loading, error, data, reload };
}
