// W4 PR-D — forgot-password entry (public). Unified anti-enumeration copy:
// success shows "if an account exists, a reset link has been sent"; the page
// never reveals whether the email is registered. Server errors are shown
// verbatim only when they are not about account existence (e.g. 429).

import { useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';

export function ForgotPasswordPage() {
  const { copy } = useLang();
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || sent) return;
    setBusy(true);
    setError('');
    try {
      await api.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.message) {
        setError(err.message);
      } else {
        setError(copy.unexpectedError);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.brand}</h1>
          <p className="mt-1 text-sm text-black/50">{copy.forgotTitle}</p>
          <form onSubmit={submit} className="mt-6 space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="forgot-email">
                {copy.email}
              </label>
              <input
                id="forgot-email"
                type="email"
                autoComplete="email"
                required
                value={email}
                disabled={sent}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm outline-none focus:border-black/30 disabled:opacity-50"
              />
            </div>
            {sent ? (
              <p className="text-sm text-black/70">{copy.forgotSent}</p>
            ) : (
              <button
                type="submit"
                disabled={busy}
                className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
              >
                {busy ? copy.loading : copy.forgotBtn}
              </button>
            )}
          </form>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          <p className="mt-4 text-center text-xs">
            <Link to="/login" className="text-black/50 underline-offset-2 hover:underline">
              {copy.backToLogin}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
