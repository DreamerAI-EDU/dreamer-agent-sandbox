// Bridge-3d — student self-login page (join code + PIN).
//
// A student has no email and no password: the teacher hands out the class
// join code and the server-drawn PIN (createInvite, Bridge-3b). Login mints
// a kid_session cookie; nothing else on this page knows about accounts.
//
// Error discipline: the server's `error` field is shown verbatim
// ("班級代碼或 PIN 不正確" / "嘗試次數過多，請稍後再試") — the frontend never
// invents its own wording and never distinguishes the failure reasons
// (that would hand a kid a probing oracle).

import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';

export function StudentLoginPage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [joinCode, setJoinCode] = useState('');
  const [pin, setPin] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);

  // Already signed in as a student? Skip the form.
  useEffect(() => {
    let alive = true;
    api
      .studentMe()
      .then(() => {
        if (alive) navigate('/student', { replace: true });
      })
      .catch(() => {
        // 401 → show the form
      })
      .finally(() => {
        if (alive) setChecking(false);
      });
    return () => {
      alive = false;
    };
  }, [navigate]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.studentLogin(joinCode.trim(), pin.trim());
      navigate('/student', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(copy.unexpectedError);
      }
    } finally {
      setBusy(false);
    }
  };

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.brand}</h1>
          <p className="mt-1 text-sm text-black/50">{copy.kidLoginTitle}</p>
          <p className="mt-1 text-xs text-black/40">{copy.kidLoginSubtitle}</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label
                className="mb-1 block text-xs font-medium text-black/60"
                htmlFor="kid-join-code"
              >
                {copy.kidJoinCode}
              </label>
              <input
                id="kid-join-code"
                type="text"
                autoComplete="off"
                autoCapitalize="characters"
                required
                value={joinCode}
                onChange={(e) => setJoinCode(e.target.value)}
                className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm uppercase tracking-widest outline-none focus:border-black/30"
              />
            </div>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-black/60"
                htmlFor="kid-pin"
              >
                {copy.kidPin}
              </label>
              <input
                id="kid-pin"
                type="password"
                inputMode="numeric"
                autoComplete="off"
                maxLength={4}
                required
                value={pin}
                onChange={(e) => setPin(e.target.value)}
                className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm tracking-[0.5em] outline-none focus:border-black/30"
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? copy.loading : copy.kidLoginBtn}
            </button>
          </form>
          <p className="mt-4 text-xs text-black/40">{copy.kidLoginNote}</p>
          <p className="mt-3 text-center text-xs">
            <Link
              to="/login"
              className="text-black/50 underline-offset-2 hover:underline"
            >
              {copy.kidBackToStaff}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}

export default StudentLoginPage;
