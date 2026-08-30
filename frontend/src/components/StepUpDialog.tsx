// W2 PR#6 — step-up re-authentication dialog (safety review detail gate).

import { useState } from 'react';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';

interface StepUpDialogProps {
  open: boolean;
  onClose: () => void;
  onVerified: () => void;
}

export function StepUpDialog({ open, onClose, onVerified }: StepUpDialogProps) {
  const { copy } = useLang();
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError('');
    try {
      await api.stepUp(password);
      setPassword('');
      onVerified();
    } catch (err) {
      if (err instanceof ApiError) {
        // Server verbatim: e.g. "email 或密碼不正確" / "嘗試次數過多，請稍後再試"
        setError(err.message);
      } else {
        setError(copy.unexpectedError);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
        <h2 className="text-lg font-semibold">{copy.safetyStepUpTitle}</h2>
        <p className="mt-1 text-sm text-black/60">{copy.safetyStepUpDesc}</p>
        <form onSubmit={submit} className="mt-4 space-y-3">
          <input
            type="password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-black/10 px-3 py-2 text-sm outline-none focus:border-black/30"
            aria-label={copy.password}
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
            >
              {copy.safetyClose}
            </button>
            <button
              type="submit"
              disabled={busy || !password}
              className="rounded-lg bg-black px-3 py-2 text-sm text-white disabled:opacity-40"
            >
              {busy ? copy.loading : copy.safetyStepUpBtn}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
