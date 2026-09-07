// W4 PR-D — reset password from the emailed link (?token=). Public page.
// Server message is shown verbatim on failure (invalid / expired token,
// weak password, rate limit). Success sends the user back to sign in.

import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import { PasswordInput } from '../components/PasswordInput';

export function ResetPasswordPage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const token = params.get('token') ?? '';
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || done) return;
    setBusy(true);
    setError('');
    try {
      await api.resetPassword(token, password);
      setDone(true);
    } catch (err) {
      if (err instanceof ApiError && err.message) {
        setError(err.message);
      } else {
        setError(copy.unexpectedError);
      }
    } finally {
      setBusy(false);
    }
  };

  if (!token) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.brand}</h1>
          <p className="mt-3 text-sm text-black/50">{copy.resetInvalid}</p>
          <p className="mt-5">
            <Link to="/login" className="text-xs text-black/50 underline-offset-2 hover:underline">
              {copy.backToLogin}
            </Link>
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.brand}</h1>
          <p className="mt-1 text-sm text-black/50">{copy.resetTitle}</p>
          {done ? (
            <div className="mt-6">
              <p className="text-sm text-black/70">{copy.resetDone}</p>
              <button
                onClick={() => navigate('/login', { replace: true })}
                className="mt-5 w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white"
              >
                {copy.loginBtn}
              </button>
            </div>
          ) : (
            <form onSubmit={submit} className="mt-6 space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="reset-password">
                  {copy.newPassword}
                </label>
                <PasswordInput
                  id="reset-password"
                  autoComplete="new-password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="mt-1 text-xs text-black/40">{copy.passwordPolicy}</p>
              </div>
              {error && <p className="text-sm text-red-600">{error}</p>}
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
              >
                {busy ? copy.loading : copy.resetBtn}
              </button>
              <p className="text-center text-xs">
                <Link to="/login" className="text-black/50 underline-offset-2 hover:underline">
                  {copy.backToLogin}
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}
