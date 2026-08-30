// W2 PR#6 — consent re-sign page (real GET /api/consent/docs + POST /api/consent/sign).

import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import type { ConsentDoc, User } from '../lib/types';
import { AppShell } from '../components/AppShell';

interface PendingDoc {
  docType: string;
  doc: ConsentDoc;
}

export function ConsentPage() {
  const { copy, lang } = useLang();
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [pending, setPending] = useState<PendingDoc[]>([]);
  const [agreed, setAgreed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [state, setState] = useState<'loading' | 'ready' | 'forbidden'>('loading');

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const me = await api.me();
        if (!alive) return;
        setUser(me.user);
        const [docsResp, statusResp] = await Promise.all([api.consentDocs(), api.consentStatus()]);
        if (!alive) return;
        const missing: PendingDoc[] = [];
        for (const [docType, doc] of Object.entries(docsResp.documents)) {
          const entry = statusResp.documents[docType];
          if (!entry || entry.status !== 'agreed') {
            missing.push({ docType, doc });
          }
        }
        if (missing.length === 0) {
          // Nothing to sign — route by role.
          if (me.user.role === 'teacher' || me.user.role === 'admin') {
            navigate('/safety', { replace: true });
          } else {
            navigate('/home', { replace: true });
          }
          return;
        }
        setPending(missing);
        setState('ready');
      } catch (err) {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          navigate('/login', { replace: true });
          return;
        }
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
        setState('forbidden');
      }
    })();
    return () => {
      alive = false;
    };
  }, [copy.unexpectedError, navigate]);

  const privacyMissing = useMemo(
    () => pending.some((p) => p.docType === 'privacy_policy'),
    [pending],
  );
  const mediaDoc = useMemo(() => pending.find((p) => p.docType === 'media_consent'), [pending]);
  const privacyAgreed = !!agreed['privacy_policy'];
  const canSubmit = !privacyMissing || privacyAgreed;

  const submit = async () => {
    if (!canSubmit || busy) return;
    setBusy(true);
    setError('');
    try {
      for (const item of pending) {
        const want = item.docType === 'privacy_policy' ? true : !!agreed[item.docType];
        if (!want) continue;
        await api.consentSign(item.docType, item.doc.current_version);
      }
      if (!user) return;
      if (user.role === 'teacher' || user.role === 'admin') {
        navigate('/safety', { replace: true });
      } else {
        navigate('/home', { replace: true });
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  if (state === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  if (!user || state === 'forbidden') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{error || copy.unexpectedError}</p>
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
        <h1 className="text-2xl font-semibold tracking-tight">{copy.consentTitle}</h1>
        <p className="mt-1 text-sm text-black/50">{copy.consentSubtitle}</p>

        <div className="mt-6 space-y-4">
          {pending.map(({ docType, doc }) => {
            const isPrivacy = docType === 'privacy_policy';
            const checked = !!agreed[docType];
            return (
              <div key={docType} className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h2 className="text-base font-semibold">
                      {langTitle(doc.title_zh, doc.title_en, lang)}
                      {doc.required && (
                        <span className="ml-2 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-normal text-amber-800">
                          {copy.consentRequired}
                        </span>
                      )}
                    </h2>
                    <p className="mt-1 text-sm text-black/50">
                      {isPrivacy ? copy.consentPrivacyDesc : copy.consentMediaDesc}
                    </p>
                    <p className="mt-1 text-xs text-black/40">Version {doc.current_version}</p>
                    <a
                      href={`/legal/${legalSlug(docType)}`}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-2 inline-block text-xs underline underline-offset-2"
                    >
                      {copy.readPolicy}
                    </a>
                  </div>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => setAgreed((prev) => ({ ...prev, [docType]: e.target.checked }))}
                      className="h-4 w-4 accent-black"
                    />
                    {isPrivacy ? copy.consentPrivacy : copy.consentMedia}
                  </label>
                </div>
              </div>
            );
          })}
        </div>

        {error && <p className="mt-4 text-sm text-red-600">{error}</p>}

        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit || busy}
          className="mt-6 w-full rounded-lg bg-black py-3 text-sm font-medium text-white disabled:opacity-40"
        >
          {busy ? copy.loading : canSubmit ? copy.consentBtn : copy.consentBtnDisabled}
        </button>
        {!privacyMissing && mediaDoc && !agreed['media_consent'] && (
          <p className="mt-2 text-center text-xs text-black/40">{copy.consentBtn}</p>
        )}
      </div>
    </AppShell>
  );
}

function legalSlug(docType: string): string {
  // Backend LEGAL_ROUTES maps hyphenated URL slugs to doc_type keys
  // (auth/consent.py): privacy_policy -> /legal/privacy-policy,
  // media_consent -> /legal/media-consent.
  return docType.replaceAll('_', '-');
}

function langTitle(titleZh: string, titleEn: string, lang: 'en' | 'hk' | 'cn'): string {
  if (lang === 'en') return titleEn;
  if (lang === 'cn') return titleZh;
  return titleZh;
}
