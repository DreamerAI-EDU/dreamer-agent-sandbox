// PR-5 A1 / A2 / A3 — the teacher's own classes + confirmed roster.
//
// One hook so the three pages that need "which class / which student" do not
// each re-walk /api/classes + /api/teacher/classes/{id}/progress. Nothing is
// invented here: class rows come from `api.classes()`, roster rows from the
// shipped class-progress endpoint (student_id is the full uuid — used only as
// a request parameter and never rendered; display goes through mask()).

import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../lib/api';
import type { TeacherClassStudent } from '../lib/teacherTypes';
import { copyEn as copy } from '../lib/i18n';

export interface RosterStudent {
  /** Full uuid — request parameter only, never rendered (mask() for display). */
  student_id: string;
  display_name: string;
  age_band: string | null;
  lang_code: string;
  class_id: string;
  class_name: string;
}

export interface RosterClass {
  id: string;
  name: string;
}

export interface TeacherRosterState {
  loading: boolean;
  error: string;
  classes: RosterClass[];
  students: RosterStudent[];
  reload: () => void;
}

/** 8-char mask of a full student uuid (last 8, same convention as the backend). */
export function mask(studentId: string): string {
  const clean = studentId.replace(/-/g, '');
  return clean.slice(-8);
}

export function useTeacherRoster(): TeacherRosterState {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [classes, setClasses] = useState<RosterClass[]>([]);
  const [students, setStudents] = useState<RosterStudent[]>([]);
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError('');
      try {
        const resp = await api.classes();
        const rows = resp.classes.map((c) => ({ id: c.id, name: c.name }));
        const progress = await Promise.all(
          rows.map((c) =>
            api
              .teacherClassProgress(c.id)
              .then((p) => ({ cls: c, students: p.students }))
              .catch(() => ({ cls: c, students: [] as TeacherClassStudent[] })),
          ),
        );
        if (!alive) return;
        const flat: RosterStudent[] = [];
        for (const entry of progress) {
          for (const s of entry.students) {
            flat.push({
              student_id: s.student_id,
              display_name: s.display_name,
              age_band: s.age_band,
              lang_code: s.lang_code,
              class_id: entry.cls.id,
              class_name: entry.cls.name,
            });
          }
        }
        setClasses(rows);
        setStudents(flat);
      } catch (err) {
        if (!alive) return;
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [nonce]);

  return useMemo(
    () => ({ loading, error, classes, students, reload }),
    [loading, error, classes, students, reload],
  );
}
