// W2 PR#6 — route gate: real session + consent check before entering.

import { useEffect, useState } from 'react';
import { Navigate, useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';

export function RootGate() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [target, setTarget] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await api.me();
        if (!alive) return;
        const status = await api.consentStatus();
        if (!alive) return;
        const privacy = status.documents['privacy_policy'];
        if (!privacy || privacy.status !== 'agreed') {
          setTarget('/consent');
          return;
        }
        if (me.user.role === 'teacher' || me.user.role === 'admin') {
          setTarget('/safety');
        } else {
          setTarget('/home');
        }
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          setTarget('/login');
          return;
        }
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      }
    })();
    return () => {
      alive = false;
    };
  }, [copy.unexpectedError, navigate]);

  if (target) return <Navigate to={target} replace />;

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{error}</p>
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="mt-4 rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
          >
            {copy.loginBtn}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
      <p className="text-sm text-black/50">{copy.loading}</p>
    </div>
  );
}
