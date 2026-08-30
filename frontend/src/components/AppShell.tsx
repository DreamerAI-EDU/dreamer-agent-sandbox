// W2 PR#6 — shared app shell for the five real pages.

import { useNavigate } from 'react-router';
import { api } from '../lib/api';
import { UI_LANGS, useLang } from '../lib/i18n';
import type { User } from '../lib/types';

interface AppShellProps {
  user: User;
  children: React.ReactNode;
}

export function AppShell({ user, children }: AppShellProps) {
  const { copy, lang, setLang } = useLang();
  const navigate = useNavigate();
  const roleLabel =
    user.role === 'teacher' ? 'Teacher' : user.role === 'admin' ? 'Admin' : 'Parent';

  const handleSignOut = async () => {
    try {
      await api.logout();
    } catch {
      // Session may already be gone — navigate regardless.
    }
    navigate('/login', { replace: true });
  };

  return (
    <div className="min-h-screen bg-[#f6f4ef]">
      <header className="sticky top-0 z-10 border-b border-black/5 bg-white/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <span className="text-base font-semibold tracking-tight">{copy.brand}</span>
            <span className="rounded-full bg-black/5 px-2 py-0.5 text-xs">{roleLabel}</span>
          </div>
          <div className="flex items-center gap-3">
            <nav className="flex items-center gap-2 text-sm">
              {UI_LANGS.map(({ code, label }) => (
                <button
                  key={code}
                  type="button"
                  onClick={() => setLang(code)}
                  className={`rounded px-2 py-1 text-xs ${
                    lang === code ? 'bg-black text-white' : 'bg-black/5 text-black/60 hover:bg-black/10'
                  }`}
                >
                  {label}
                </button>
              ))}
            </nav>
            <span className="max-w-[220px] truncate text-xs text-black/50">{user.email}</span>
            <button
              type="button"
              onClick={handleSignOut}
              className="rounded border border-black/10 px-2.5 py-1 text-xs hover:bg-black/5"
            >
              {copy.signOut}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-8">{children}</main>
    </div>
  );
}
