// W2 PR#6 — invite landing page (real GET /api/invites/{token} + POST confirm).
// The confirm POST is CSRF-exempt by backend design — it must NOT send
// X-Requested-With (mock-mapping §1).

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import { PasswordInput } from '../components/PasswordInput';
import type { InvitePublic } from '../lib/types';

// Backend LANG_CODES: en / zh-hk / zh-cn. The invite's UI language is fixed
// by the teacher when the invite is created (confirm POST carries no
// lang_code) — this row is read-only display of the fourth public field.
const LANG_LABELS: Record<string, string> = {
  en: 'English',
  'zh-hk': '繁體中文',
  'zh-cn': '简体中文',
};

type InviteState =
  | { phase: 'loading' }
  | { phase: 'form'; info: InvitePublic }
  | { phase: 'invalid'; message: string };

export function InvitePage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const { token = '' } = useParams<{ token: string }>();
  const [state, setState] = useState<InviteState>({ phase: 'loading' });
  const [password, setPassword] = useState('');
  const [privacyAgreed, setPrivacyAgreed] = useState(false);
  const [mediaAgreed, setMediaAgreed] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    api
      .invitePublic(token)
      .then((info) => {
        if (alive) setState({ phase: 'form', info });
      })
      .catch((err: unknown) => {
        if (!alive) return;
        if (err instanceof ApiError) {
          setState({ phase: 'invalid', message: err.message });
        } else {
          setState({ phase: 'invalid', message: copy.unexpectedError });
        }
      });
    return () => {
      alive = false;
    };
  }, [copy.unexpectedError, token]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy || !privacyAgreed) return;
    setBusy(true);
    setError('');
    try {
      await api.inviteConfirm(token, {
        password,
        privacy_policy: privacyAgreed,
        // W6 PR-D: the single required checkbox binds BOTH required
        // consents — privacy_policy + chat_consent. Backend rejects
        // half-sign callers.
        chat_consent: privacyAgreed,
        media_consent: mediaAgreed,
      });
      navigate('/home', { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        // Server verbatim: invalid/expired link, weak password, etc.
        setError(err.message);
      } else {
        setError(copy.unexpectedError);
      }
    } finally {
      setBusy(false);
    }
  };

  if (state.phase === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  if (state.phase === 'invalid') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <h1 className="text-lg font-semibold">{copy.inviteInvalidTitle}</h1>
          <p className="mt-2 text-sm text-black/60">{state.message}</p>
          <p className="mt-4 text-xs text-black/40">
            {copy.contactEmail}: info@dreamer-aiedu.com
          </p>
        </div>
      </div>
    );
  }

  const { info } = state;
  const ageLabel = copy.ageBands[info.age_band] ?? info.age_band;

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
      <div className="w-full max-w-sm">
        <div className="rounded-2xl border border-black/5 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold tracking-tight">{copy.inviteTitle}</h1>
          <p className="mt-1 text-sm text-black/50">{copy.inviteSubtitle}</p>

          <dl className="mt-5 space-y-2 rounded-xl bg-black/5 p-4 text-sm">
            <div className="flex justify-between">
              <dt className="text-black/50">{copy.inviteName}</dt>
              <dd className="font-medium">{info.first_name}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-black/50">{copy.inviteBandLabel}</dt>
              <dd className="font-medium">{ageLabel}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-black/50">{copy.inviteEmail}</dt>
              <dd className="max-w-[200px] truncate font-medium">{info.parent_email}</dd>
            </div>
            <div className="flex justify-between">
              <dt className="text-black/50">{copy.inviteLang}</dt>
              <dd className="font-medium">{LANG_LABELS[info.lang_code] ?? info.lang_code}</dd>
            </div>
          </dl>

          <form onSubmit={submit} className="mt-5 space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-black/60" htmlFor="invite-password">
                {copy.invitePasswordHint}
              </label>
              <PasswordInput
                id="invite-password"
                autoComplete="new-password"
                required
                minLength={10}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              <p className="mt-1 text-xs text-black/40">{copy.passwordPolicy}</p>
            </div>

            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={privacyAgreed}
                onChange={(e) => setPrivacyAgreed(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-black"
              />
              <span>
                <span>
                  {copy.invitePrivacyMust}{' '}
                  <span className="text-black/40">{copy.inviteConsentRequiredTag}</span>
                </span>
                <span className="mt-0.5 block text-xs text-black/50">
                  <a href="/legal/privacy-policy" target="_blank" rel="noreferrer" className="underline underline-offset-2">
                    {copy.consentPrivacy}
                  </a>
                  {' · '}
                  <a href="/legal/chat-consent" target="_blank" rel="noreferrer" className="underline underline-offset-2">
                    {copy.consentChat}
                  </a>
                </span>
              </span>
            </label>
            <label className="flex items-start gap-2 text-sm">
              <input
                type="checkbox"
                checked={mediaAgreed}
                onChange={(e) => setMediaAgreed(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-black"
              />
              <span>
                <span>
                  {copy.inviteMedia}{' '}
                  <span className="text-black/40">{copy.inviteConsentOptionalTag}</span>
                </span>
                <a href="/legal/media-consent" target="_blank" rel="noreferrer" className="mt-0.5 block text-xs underline underline-offset-2 text-black/50">
                  {copy.readPolicy}
                </a>
              </span>
            </label>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <button
              type="submit"
              disabled={busy || !privacyAgreed}
              className="w-full rounded-lg bg-black py-2.5 text-sm font-medium text-white disabled:opacity-40"
            >
              {busy ? copy.loading : copy.inviteBtn}
            </button>
          </form>
        </div>
        <p className="mt-4 text-center text-xs text-black/40">{copy.brand}</p>
      </div>
    </div>
  );
}
