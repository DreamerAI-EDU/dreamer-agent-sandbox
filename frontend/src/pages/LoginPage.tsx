// W2 PR#6 — login page (real POST /api/auth/login).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import { PasswordInput } from '../components/PasswordInput';
import type { User } from '../lib/types';

export function LoginPage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [checking, setChecking] = useState(true);

  // Already signed in? Skip the form.
  useEffect(() => {
    let alive = true;
    api
      .me()
      .then((me) => {
        if (!alive) return;
        if (me.user.role === 'teacher') {
          navigate('/teacher', { replace: true });
        } else if (me.user.role === 'admin') {
          navigate('/safety', { replace: true });
        } else {
          navigate('/home', { replace: true });
        }
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
      const resp = await api.login(email.trim(), password);
      if (resp.consent_required) {
        navigate('/consent', { replace: true });
        return;
      }
      if (resp.user.role === 'teacher') {
        navigate('/teacher', { replace: true });
      } else if (resp.user.role === 'admin') {
        navigate('/safety', { replace: true });
      } else {
        navigate('/home', { replace: true });
      }
    } catch (err) {
      if (err instanceof ApiError) {
        // Server verbatim: "email 或密碼不正確" / "嘗試次數過多，請稍後再試"
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
          <p className="mt-1 text-sm text-black/50">{copy.loginTitle}</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="login-email">
                {copy.email}
              </label>
              <input
                id="login-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm outline-none focus:border-black/30"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="login-password">
                {copy.password}
              </label>
              <PasswordInput
                id="login-password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? copy.loading : copy.loginBtn}
            </button>
          </form>
          <p className="mt-4 text-xs text-black/40">{copy.loginNote}</p>
        </div>
      </div>
    </div>
  );
}

// Helper used by route gates — typed me() for callers that need the user.
export async function fetchCurrentUser(): Promise<User | null> {
  try {
    const me = await api.me();
    return me.user;
  } catch {
    return null;
  }
}
