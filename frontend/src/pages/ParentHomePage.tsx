// W2 PR#6 — parent home: student list + PIN gate + PIN reset.
// Full student ids never leave the server; only the 8-char mask prefix is
// used here and passed to the chat route (never stored in localStorage).

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import type { Student, User } from '../lib/types';
import { AppShell } from '../components/AppShell';

export function ParentHomePage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [loadError, setLoadError] = useState('');
  const [selected, setSelected] = useState<Student | null>(null);
  const [pin, setPin] = useState('');
  const [pinError, setPinError] = useState('');
  const [pinBusy, setPinBusy] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [resetMode, setResetMode] = useState<'self' | 'generate'>('self');
  const [newPin, setNewPin] = useState('');
  const [generatedPin, setGeneratedPin] = useState('');
  const [resetError, setResetError] = useState('');
  const [resetBusy, setResetBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const me = await api.me();
      if (me.user.role === 'teacher' || me.user.role === 'admin') {
        navigate('/safety', { replace: true });
        return;
      }
      setUser(me.user);
      const resp = await api.students();
      setStudents(resp.students);
      setLoadError('');
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        navigate('/login', { replace: true });
        return;
      }
      setLoadError(err instanceof ApiError ? err.message : copy.unexpectedError);
    }
  }, [copy.unexpectedError, navigate]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectStudent = (student: Student) => {
    setSelected(student);
    setPin('');
    setPinError('');
  };

  const closePin = () => {
    setSelected(null);
    setPin('');
    setPinError('');
  };

  const verifyPin = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected || pinBusy) return;
    if (!/^\d{4}$/.test(pin)) {
      setPinError(copy.pinSubtitle);
      return;
    }
    setPinBusy(true);
    setPinError('');
    try {
      await api.pinVerify(selected.id, pin);
      // Mask prefix only — never the full student id.
      const params = new URLSearchParams({
        student: selected.id,
        name: selected.first_name,
        band: selected.age_band,
      });
      navigate(`/chat?${params.toString()}`);
    } catch (err) {
      if (err instanceof ApiError) {
        // Server verbatim: "PIN 不正確" (401) / "等待老師確認" (403) / 429 lockout.
        setPinError(err.message);
      } else {
        setPinError(copy.unexpectedError);
      }
    } finally {
      setPinBusy(false);
    }
  };

  const openReset = () => {
    setResetOpen(true);
    setResetMode('self');
    setNewPin('');
    setGeneratedPin('');
    setResetError('');
  };

  const submitReset = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selected || resetBusy) return;
    const selfPin = resetMode === 'self' ? newPin.trim() : undefined;
    if (resetMode === 'self' && !/^\d{4}$/.test(selfPin ?? '')) {
      setResetError(copy.pinSubtitle);
      return;
    }
    setResetBusy(true);
    setResetError('');
    try {
      const resp = await api.pinReset(selected.id, selfPin);
      if (resp.pin !== undefined) {
        // Server-generated PIN — show once, never logged.
        setGeneratedPin(resp.pin);
      } else {
        closePin();
        setResetOpen(false);
      }
    } catch (err) {
      if (err instanceof ApiError) {
        setResetError(err.message);
      } else {
        setResetError(copy.unexpectedError);
      }
    } finally {
      setResetBusy(false);
    }
  };

  if (!user && !loadError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{loadError}</p>
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
    <AppShell user={user}>
      <div className="mx-auto max-w-xl">
        <h1 className="text-2xl font-semibold tracking-tight">{copy.homeTitle}</h1>
        <p className="mt-1 text-sm text-black/50">{copy.homeSubtitle}</p>

        {students.length === 0 ? (
          <p className="mt-8 rounded-2xl border border-dashed border-black/10 p-8 text-center text-sm text-black/50">
            {copy.noStudents}
          </p>
        ) : (
          <ul className="mt-6 space-y-3">
            {students.map((student) => (
              <li key={student.id}>
                <button
                  type="button"
                  onClick={() => selectStudent(student)}
                  className="flex w-full items-center justify-between rounded-2xl border border-black/5 bg-white p-5 text-left shadow-sm transition hover:border-black/20"
                >
                  <div>
                    <div className="text-base font-semibold">{student.first_name}</div>
                    <div className="mt-0.5 text-xs text-black/40">
                      {copy.ageBands[student.age_band] ?? student.age_band} · {student.id}
                    </div>
                  </div>
                  <span className="text-sm text-black/40">{copy.pinTitle} →</span>
                </button>
              </li>
            ))}
          </ul>
        )}

        {selected && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
              <h2 className="text-lg font-semibold">{copy.pinTitle}</h2>
              <p className="mt-1 text-sm text-black/60">
                {copy.pinSubtitle} ({selected.first_name})
              </p>
              <form onSubmit={verifyPin} className="mt-4 space-y-3">
                <input
                  type="password"
                  inputMode="numeric"
                  pattern="[0-9]{4}"
                  maxLength={4}
                  autoFocus
                  value={pin}
                  onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))}
                  className="w-full rounded-lg border border-black/10 px-3 py-2 text-center text-lg tracking-[0.5em] outline-none focus:border-black/30"
                  placeholder="••••"
                  aria-label={copy.pinPlaceholder}
                />
                {pinError && <p className="text-sm text-red-600">{pinError}</p>}
                <div className="flex justify-between gap-2">
                  <button
                    type="button"
                    onClick={openReset}
                    className="rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
                  >
                    {copy.pinResetBtn}
                  </button>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={closePin}
                      className="rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
                    >
                      {copy.pinCancel}
                    </button>
                    <button
                      type="submit"
                      disabled={pinBusy || pin.length !== 4}
                      className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {pinBusy ? copy.loading : copy.pinVerifyBtn}
                    </button>
                  </div>
                </div>
              </form>
            </div>
          </div>
        )}

        {resetOpen && selected && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
            <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
              <h2 className="text-lg font-semibold">{copy.pinResetTitle}</h2>
              <form onSubmit={submitReset} className="mt-4 space-y-4">
                <div className="space-y-2">
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="reset-mode"
                      checked={resetMode === 'self'}
                      onChange={() => setResetMode('self')}
                      className="accent-black"
                    />
                    {copy.pinResetSelf}
                  </label>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="radio"
                      name="reset-mode"
                      checked={resetMode === 'generate'}
                      onChange={() => setResetMode('generate')}
                      className="accent-black"
                    />
                    {copy.pinResetGenerate}
                  </label>
                </div>

                {resetMode === 'self' && (
                  <input
                    type="password"
                    inputMode="numeric"
                    pattern="[0-9]{4}"
                    maxLength={4}
                    value={newPin}
                    onChange={(e) => setNewPin(e.target.value.replace(/\D/g, ''))}
                    className="w-full rounded-lg border border-black/10 px-3 py-2 text-center text-lg tracking-[0.5em] outline-none focus:border-black/30"
                    placeholder="••••"
                    aria-label={copy.pinNewPin}
                  />
                )}

                {resetMode === 'generate' && (
                  <p className="rounded-xl bg-black/5 p-3 text-xs text-black/60">
                    {copy.pinResetGenerateDesc}
                  </p>
                )}

                {generatedPin && (
                  <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-center">
                    <p className="text-xs text-green-700">{copy.pinNewPin}</p>
                    <p className="mt-1 text-2xl font-semibold tracking-[0.4em]">{generatedPin}</p>
                    <p className="mt-1 text-xs text-green-700">{copy.pinSaveNotice}</p>
                    <button
                      type="button"
                      onClick={() => {
                        closePin();
                        setResetOpen(false);
                        setGeneratedPin('');
                      }}
                      className="mt-3 rounded-lg bg-black px-4 py-1.5 text-sm text-white"
                    >
                      {copy.pinCancel}
                    </button>
                  </div>
                )}

                {!generatedPin && resetError && <p className="text-sm text-red-600">{resetError}</p>}

                {!generatedPin && (
                  <div className="flex justify-end gap-2">
                    <button
                      type="button"
                      onClick={() => setResetOpen(false)}
                      className="rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
                    >
                      {copy.pinCancel}
                    </button>
                    <button
                      type="submit"
                      disabled={resetBusy}
                      className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-40"
                    >
                      {resetBusy ? copy.loading : copy.pinResetSubmit}
                    </button>
                  </div>
                )}
              </form>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
