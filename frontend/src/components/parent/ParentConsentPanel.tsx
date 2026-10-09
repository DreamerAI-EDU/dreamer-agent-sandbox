// W6 PR-E — per-child consent & withdrawal panel.
//
// The parent dashboard previously showed no consent state at all (the old
// ConsentIndicator is a teacher-console media lamp). PR-E lands the
// decoupled per-consent withdraw path where the parent *perceives* it:
// one row per withdrawable consent (chat_consent, media_consent) with an
// independent "Withdraw" action and a confirm dialog whose consequence
// copy differs per doc:
//   - chat_consent  → AI chat stops immediately for this child
//   - media_consent → collected media is taken down within 24 hours
//
// Data source: GET /api/consent/status?student=<mask> (per-student rows +
// account-level NULL rows, latest row decides). Withdraw posts the 8-char
// mask; the backend resolves it inside the parent's reachable set — the
// full id never leaves the server (auth/api.py _consent_resolve_student).
//
// P0-a (2026-10-09) — the panel used to render a button only for `agreed`
// rows, so a parent could never *create* consent from inside the app: the
// voluntary voice_consent (mic stays hidden until signed) and any
// withdrawn-then-changed-mind doc were dead ends. Every non-agreed row now
// carries an independent "Sign" action, mirroring the withdraw path:
// POST /api/consent/sign with the doc's *current* version (the status
// response carries it, so the panel never hard-codes a version string).

import { useCallback, useEffect, useState } from 'react';
import { api } from '../../lib/api';
import { useLang } from '../../lib/i18n';
import type { ConsentStatusEntry } from '../../lib/types';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '../ui/dialog';
import type { ConsentStatus } from './ConsentIndicator';

type WithdrawableDoc = 'chat_consent' | 'media_consent' | 'voice_consent';

interface RowSpec {
  doc: WithdrawableDoc;
  labelKey: 'consentChat' | 'consentMedia' | 'consentVoice';
  effectKey: 'consentChatEffect' | 'consentMediaEffect' | 'consentVoiceEffect';
}

const ROWS: RowSpec[] = [
  { doc: 'chat_consent', labelKey: 'consentChat', effectKey: 'consentChatEffect' },
  { doc: 'media_consent', labelKey: 'consentMedia', effectKey: 'consentMediaEffect' },
  // c1-13b: voice consent has its own row — withdrawing it stops the mic for
  // this child and leaves every text feature untouched.
  { doc: 'voice_consent', labelKey: 'consentVoice', effectKey: 'consentVoiceEffect' },
];

const DOT: Record<ConsentStatus, string> = {
  agreed: 'bg-emerald-500',
  unsigned: 'bg-slate-400',
  withdrawn: 'bg-amber-500',
};

interface Props {
  /** 8-char masked Student.id (the only shape /api/students exposes). */
  studentId: string;
}

export function ParentConsentPanel({ studentId }: Props) {
  const { copy } = useLang();
  const [documents, setDocuments] = useState<Record<string, ConsentStatusEntry> | null>(null);
  const [error, setError] = useState('');
  const [pendingDoc, setPendingDoc] = useState<WithdrawableDoc | null>(null);
  const [withdrawing, setWithdrawing] = useState(false);
  const [pendingSign, setPendingSign] = useState<WithdrawableDoc | null>(null);
  const [signing, setSigning] = useState(false);
  const [notice, setNotice] = useState('');
  const [noticeKind, setNoticeKind] = useState<'ok' | 'error'>('ok');

  const load = useCallback(async () => {
    setError('');
    try {
      const resp = await api.consentStatus(studentId);
      setDocuments(resp.documents);
    } catch {
      setError(copy.unexpectedError);
    }
  }, [copy.unexpectedError, studentId]);

  useEffect(() => {
    setDocuments(null);
    setNotice('');
    setPendingDoc(null);
    setPendingSign(null);
    void load();
  }, [load]);

  const runWithdraw = useCallback(async () => {
    if (!pendingDoc) return;
    setWithdrawing(true);
    setNotice('');
    try {
      await api.consentWithdraw(pendingDoc, studentId);
      setNoticeKind('ok');
      setNotice(copy.consentWithdrawSuccess);
      setPendingDoc(null);
      await load();
    } catch {
      setNoticeKind('error');
      setNotice(copy.consentWithdrawFailed);
    } finally {
      setWithdrawing(false);
    }
  }, [copy.consentWithdrawFailed, copy.consentWithdrawSuccess, load, pendingDoc, studentId]);

  // P0-a: the sign path needs the doc's current version — taken from the same
  // status response that decides what gets rendered (single source of truth).
  const runSign = useCallback(async () => {
    if (!pendingSign) return;
    const entry = documents?.[pendingSign];
    if (!entry) return;
    setSigning(true);
    setNotice('');
    try {
      await api.consentSign(entry.doc_type, entry.current_version);
      setNoticeKind('ok');
      setNotice(copy.consentSignSuccess);
      setPendingSign(null);
      await load();
    } catch {
      setNoticeKind('error');
      setNotice(copy.consentSignFailed);
    } finally {
      setSigning(false);
    }
  }, [copy.consentSignFailed, copy.consentSignSuccess, documents, load, pendingSign]);

  const pendingSpec = ROWS.find((r) => r.doc === pendingDoc) ?? null;
  const pendingSignSpec = ROWS.find((r) => r.doc === pendingSign) ?? null;
  const pendingSignVersion = pendingSign ? documents?.[pendingSign]?.current_version ?? '' : '';

  return (
    <section className="rounded-2xl border border-black/10 bg-white px-4 py-3">
      <h2 className="text-sm font-semibold text-[#00023D]">{copy.consentPanelTitle}</h2>
      {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
      {!documents && !error && (
        <p className="mt-2 text-xs text-black/40">{copy.loading}</p>
      )}
      {documents && (
        <ul className="mt-2 space-y-2">
          {ROWS.map((row) => {
            const entry = documents[row.doc];
            if (!entry) return null;
            const status: ConsentStatus = entry.status;
            return (
              <li
                key={row.doc}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-black/5 bg-[#fafaf7] px-3 py-2"
              >
                <div className="flex items-center gap-2 text-xs">
                  <span
                    className={`h-2 w-2 rounded-full ${DOT[status]}`}
                    aria-hidden
                  />
                  <span className="font-medium text-black/80">{copy[row.labelKey]}</span>
                  <span className="text-black/50">
                    {status === 'agreed' && copy.consentAgreed}
                    {status === 'unsigned' && copy.consentNotSigned}
                    {status === 'withdrawn' && copy.consentWithdrawn}
                  </span>
                </div>
                {status === 'agreed' ? (
                  <button
                    type="button"
                    onClick={() => setPendingDoc(row.doc)}
                    disabled={withdrawing || signing}
                    className="rounded-full border border-black/15 bg-white px-3 py-1 text-xs font-semibold text-[#00023D] transition-colors hover:border-[#00023D] disabled:opacity-50"
                  >
                    {copy.consentWithdrawBtn}
                  </button>
                ) : (
                  // P0-a: unsigned / withdrawn rows get their own way in —
                  // without this the voluntary voice_consent could only ever
                  // be signed during signup, which never showed it at all.
                  <button
                    type="button"
                    onClick={() => setPendingSign(row.doc)}
                    disabled={withdrawing || signing}
                    className="rounded-full bg-[#00023D] px-3 py-1 text-xs font-semibold text-white transition-colors hover:bg-[#00023D]/90 disabled:opacity-50"
                  >
                    {copy.consentSignBtn}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {documents && ROWS.every((row) => !documents[row.doc]) && (
        <p className="mt-2 text-xs text-black/40">{copy.consentPanelEmpty}</p>
      )}
      {notice && (
        <p
          className={`mt-2 text-xs ${noticeKind === 'ok' ? 'text-emerald-700' : 'text-red-600'}`}
        >
          {notice}
        </p>
      )}

      <Dialog open={pendingSpec !== null} onOpenChange={(open) => !open && setPendingDoc(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{copy.consentDialogTitle}</DialogTitle>
            <DialogDescription className="pt-1">
              {pendingSpec && copy[pendingSpec.effectKey]}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <button
              type="button"
              onClick={() => setPendingDoc(null)}
              disabled={withdrawing}
              className="rounded-full border border-black/15 bg-white px-4 py-1.5 text-sm font-semibold text-black/70 disabled:opacity-50"
            >
              {copy.consentDialogCancel}
            </button>
            <button
              type="button"
              onClick={() => void runWithdraw()}
              disabled={withdrawing}
              className="rounded-full bg-[#00023D] px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {withdrawing ? copy.consentWithdrawingBtn : copy.consentDialogConfirm}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* P0-a: sign confirm — same shape as the withdraw dialog, but the
          description names the document (+ its version) instead of a
          consequence, because signing *grants* a capability. */}
      <Dialog open={pendingSignSpec !== null} onOpenChange={(open) => !open && setPendingSign(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{copy.consentSignDialogTitle}</DialogTitle>
            <DialogDescription className="pt-1">
              {pendingSignSpec && copy[pendingSignSpec.labelKey]}
              {pendingSignVersion && ` · ${pendingSignVersion}`}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2">
            <button
              type="button"
              onClick={() => setPendingSign(null)}
              disabled={signing}
              className="rounded-full border border-black/15 bg-white px-4 py-1.5 text-sm font-semibold text-black/70 disabled:opacity-50"
            >
              {copy.consentDialogCancel}
            </button>
            <button
              type="button"
              onClick={() => void runSign()}
              disabled={signing}
              className="rounded-full bg-[#00023D] px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-50"
            >
              {signing ? copy.consentSigningBtn : copy.consentSignDialogConfirm}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
