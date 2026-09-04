// W3-C — teacher register page (invite-only, launch gate).
// Flow: invite code + email + password → register → email verification
// code (single-use, sent by backend) → verified → sign in → /teacher.
// The page is intentionally minimal: no resend, no admin paths.

import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { copyEn as copy } from '../lib/i18n';
import { PasswordInput } from '../components/PasswordInput';

type Step = 'form' | 'verify' | 'done';

function isWeakPassword(pw: string): boolean {
  if (pw.length < 10) return true;
  if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return true;
  return false;
}

export function TeacherRegisterPage() {
  const navigate = useNavigate();

  const [step, setStep] = useState<Step>('form');
  const [inviteCode, setInviteCode] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submitRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    if (isWeakPassword(password)) {
      setError(copy.passwordPolicy);
      return;
    }
    setBusy(true);
    setError('');
    try {
      await api.register(inviteCode.trim(), email.trim(), password);
      setStep('verify');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const submitVerify = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await api.verifyEmail(code.trim());
      setStep('done');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const inputCls =
    'w-full rounded-lg border border-black/10 px-3 py-2 text-sm outline-none focus:border-black/30';

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.brand}</h1>

          {step === 'form' && (
            <>
              <p className="mt-1 text-sm text-black/50">{copy.teacherRegisterTitle}</p>
              <p className="mt-2 text-xs text-black/40">{copy.teacherRegisterSubtitle}</p>
              <form onSubmit={submitRegister} className="mt-6 space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="treg-code">
                    {copy.inviteCodeLabel}
                  </label>
                  <input
                    id="treg-code"
                    type="text"
                    autoComplete="off"
                    required
                    value={inviteCode}
                    onChange={(e) => setInviteCode(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="treg-email">
                    {copy.email}
                  </label>
                  <input
                    id="treg-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className={inputCls}
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="treg-password">
                    {copy.password}
                  </label>
                  <PasswordInput
                    id="treg-password"
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
                  {busy ? copy.loading : copy.registerBtn}
                </button>
              </form>
              <p className="mt-4 text-center text-xs text-black/40">
                {copy.alreadyHaveAccount}{' '}
                <Link to="/login" className="text-black/70 underline">
                  {copy.loginBtn}
                </Link>
              </p>
            </>
          )}

          {step === 'verify' && (
            <>
              <p className="mt-1 text-sm text-black/50">{copy.verifyTitle}</p>
              <p className="mt-2 text-xs text-black/40">
                {copy.verifySubtitle} {email.trim().toLowerCase()}
              </p>
              <form onSubmit={submitVerify} className="mt-6 space-y-4">
                <div>
                  <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="treg-code-verify">
                    {copy.verifyCodeLabel}
                  </label>
                  <input
                    id="treg-code-verify"
                    type="text"
                    autoComplete="one-time-code"
                    required
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    className={inputCls}
                  />
                </div>
                {error && <p className="text-sm text-red-600">{error}</p>}
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
                >
                  {busy ? copy.loading : copy.verifyBtn}
                </button>
              </form>
              <p className="mt-4 text-xs text-black/40">{copy.registerNote}</p>
            </>
          )}

          {step === 'done' && (
            <div className="mt-6 text-center">
              <p className="text-sm font-medium text-black/80">{copy.verifyDoneTitle}</p>
              <p className="mt-2 text-xs text-black/50">{copy.verifyDoneDesc}</p>
              <button
                type="button"
                onClick={() => navigate('/login', { replace: true })}
                className="mt-5 w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white"
              >
                {copy.goLogin}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
