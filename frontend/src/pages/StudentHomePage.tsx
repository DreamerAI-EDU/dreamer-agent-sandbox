// Bridge-3d — the student's own learning space (kid_session only).
//
// Deliberately thin: identity + the shared Week X / 8 badge + the current
// unit title. Everything here comes from GET /api/student/me, i.e. the same
// curriculum.student_week_badge resolver the kid badge on the parent side
// reads (Bridge-3a) — parent and child can never be told two different
// weeks (ruling #3: the backend states the week, the frontend never
// derives it). Classmates' mastery is NOT here: a class average is a
// teacher-facing number and must never reach a kid.
//
// 401 (expired / cleared session) sends the student back to the login page.

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import type { StudentMeResponse } from '../lib/types';

export function StudentHomePage() {
  const { copy, setLang } = useLang();
  const navigate = useNavigate();
  const [home, setHome] = useState<StudentMeResponse | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .studentMe()
      .then((data) => {
        if (!alive) return;
        setHome(data);
        // PR-0 i18n fix: the student's saved lang_code drives the UI language
        // (zh-hk accounts no longer see the English console by default).
        const lc = data.student?.lang_code;
        if (lc === 'zh-hk') setLang('hk');
        else if (lc === 'zh-cn') setLang('cn');
        else if (lc === 'en') setLang('en');
      })
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/student/login', { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      });
    return () => {
      alive = false;
    };
  }, [copy.unexpectedError, navigate]);

  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.studentLogout();
    } catch {
      // Even if the call fails the cookie is not refreshed; send them back
      // to the form rather than leaving a dead screen.
    } finally {
      navigate('/student/login', { replace: true });
    }
  };

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{error}</p>
          <button
            type="button"
            onClick={() => navigate('/student/login', { replace: true })}
            className="mt-4 w-full rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
          >
            {copy.kidLoginBtn}
          </button>
        </div>
      </div>
    );
  }

  if (!home) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  const { student, class: kidClass, badge } = home;

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-md">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <p className="text-xs uppercase tracking-widest text-black/40">
            {copy.kidHomeTitle}
          </p>
          <h1 className="mt-2 text-xl font-semibold tracking-tight">
            {student ? student.first_name : copy.brand}
          </h1>
          {kidClass && (
            <p className="mt-1 text-sm text-black/50">{kidClass.name}</p>
          )}

          <div className="mt-6 rounded-xl border border-black/5 bg-[#f6f4ef] p-5">
            {badge.state === 'none' ? (
              <p className="text-sm text-black/50">{copy.kidNoCourse}</p>
            ) : (
              <>
                <p className="text-3xl font-semibold tracking-tight">
                  {badge.state === 'completed'
                    ? `${badge.total_weeks} / ${badge.total_weeks}`
                    : `${copy.kidWeek} ${badge.week_index} / ${badge.total_weeks}`}
                </p>
                {badge.unit_title && (
                  <p className="mt-2 text-sm text-black/60">{badge.unit_title}</p>
                )}
              </>
            )}
          </div>

          {student && (
            <button
              type="button"
              onClick={() =>
                navigate(
                  `/chat?student=${encodeURIComponent(
                    student.id.slice(0, 8)
                  )}&name=${encodeURIComponent(
                    student.first_name
                  )}&band=${encodeURIComponent(student.age_band)}&from=student`
                )
              }
              className="mt-4 w-full rounded-xl bg-black px-4 py-4 text-left text-white shadow-sm hover:bg-black/85"
            >
              <p className="text-lg font-semibold tracking-tight">
                {copy.kidStartLesson}
              </p>
              <p className="mt-1 text-sm text-white/70">
                {copy.kidStartLessonDesc}
              </p>
            </button>
          )}

          <button
            type="button"
            onClick={signOut}
            disabled={busy}
            className="mt-6 w-full rounded-lg border border-black/10 py-2 text-sm hover:bg-black/5 disabled:opacity-40"
          >
            {copy.kidLogout}
          </button>
        </div>
      </div>
    </div>
  );
}

export default StudentHomePage;
