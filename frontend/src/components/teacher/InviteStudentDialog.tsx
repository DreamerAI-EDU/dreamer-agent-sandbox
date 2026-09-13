// Bridge-3c — 邀請 entry (掣 3): the teacher console's entry point into the
// PRE-EXISTING invite flow. Nothing about the flow is reimplemented here.
//
//   POST /api/invites  {class_id, first_name, age_band, lang_code,
//                       parent_email, pin?}
//     -> 201 {message, pin?}
//
// One call, server-side: creates the student, the pending class membership
// and the 72h invite, then emails the parent the /invite/{token} link
// (auth/classes.py send_invite_email). The token never reaches the browser —
// the response carries only the server's own message and, when the server
// generated the PIN, that PIN once. So the dialog shows exactly those two
// things and copies the PIN to the clipboard for hand-off; it does not
// invent a "link" the API does not return, and it calls no resend/withdraw
// endpoint (v1 scope: create + what the server handed back).
//
// UI zero logic: no client-side invite state machine, no fabricated wording
// — every error string is the server's own (`error` surfaced verbatim by
// api.ts), and the age band / language vocabularies are the backend's own
// AGE_BANDS / LANG_CODES.
//
// Teacher-facing UI is pinned to English (copyEn) — same policy as the rest
// of the teacher console (W3-C).

import { useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { copyEn as copy } from '../../lib/i18n';
import type { CreateInviteResponse } from '../../lib/types';

/** Mirrors auth/api.py AGE_BANDS — the server re-validates regardless. */
const AGE_BANDS = ['P1-P3', 'P4-P6', 'S1-S3'] as const;
/** Mirrors auth/api.py LANG_CODES — the server re-validates regardless. */
const LANG_CODES = ['en', 'zh-hk', 'zh-cn'] as const;

const PIN_RE = /^\d{4}$/;

interface InviteStudentDialogProps {
  classId: string;
  onClose: () => void;
  /** An invite was created — the roster/pending lists may have moved. */
  onInvited?: () => void;
}

export function InviteStudentDialog({ classId, onClose, onInvited }: InviteStudentDialogProps) {
  const [firstName, setFirstName] = useState('');
  const [ageBand, setAgeBand] = useState<string>(AGE_BANDS[0]);
  const [langCode, setLangCode] = useState<string>('zh-hk');
  const [parentEmail, setParentEmail] = useState('');
  const [pin, setPin] = useState('');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sent, setSent] = useState<CreateInviteResponse | null>(null);
  const [copied, setCopied] = useState(false);

  const trimmedPin = pin.trim();
  const pinInvalid = trimmedPin !== '' && !PIN_RE.test(trimmedPin);
  const canSubmit =
    !busy && firstName.trim() !== '' && parentEmail.trim() !== '' && !pinInvalid;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    setError('');
    try {
      const resp = await api.createInvite({
        class_id: classId,
        first_name: firstName.trim(),
        age_band: ageBand,
        lang_code: langCode,
        parent_email: parentEmail.trim(),
        // Omitted (not empty) when blank: the server then generates the PIN
        // and returns it once.
        ...(trimmedPin !== '' ? { pin: trimmedPin } : {}),
      });
      setSent(resp);
      onInvited?.();
    } catch (err) {
      // 400 / 403 / 429 — the server's own wording, shown as-is.
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const copyPin = async () => {
    if (!sent?.pin) return;
    try {
      await navigator.clipboard.writeText(sent.pin);
      setCopied(true);
    } catch {
      // Clipboard unavailable (insecure context / denied): the PIN stays
      // visible on screen, so no error state is needed.
    }
  };

  const fieldCls =
    'mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-[#00023D]/40';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-2xl border border-black/5 bg-white p-6 shadow-lg">
        <h2 className="text-base font-semibold tracking-tight text-[#00023D]">
          {copy.inviteStudentTitle}
        </h2>

        {sent ? (
          <div className="mt-4 space-y-3">
            <p className="text-sm font-medium text-black/80">{copy.inviteSentTitle}</p>
            <p className="text-sm text-black/60">{sent.message}</p>
            <p className="text-xs text-black/50">{copy.inviteSentEmailNote}</p>

            {sent.pin && (
              <div className="rounded-xl bg-black/5 px-3 py-3">
                <p className="text-xs text-black/60">{copy.inviteSentPinNote}</p>
                <div className="mt-2 flex items-center justify-between gap-3">
                  <span className="font-mono text-lg tracking-widest text-[#00023D]">
                    {sent.pin}
                  </span>
                  <button
                    type="button"
                    onClick={() => void copyPin()}
                    className="rounded-lg border border-black/10 px-3 py-1.5 text-xs text-black/70 transition-colors hover:bg-white"
                  >
                    {copied ? copy.inviteCopied : copy.inviteCopyPinBtn}
                  </button>
                </div>
              </div>
            )}

            <p className="text-xs text-black/45">{copy.invitePendingNote}</p>

            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                {copy.closeBtn}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            <p className="text-xs text-black/50">{copy.inviteStudentHint}</p>

            {error && <p className="text-sm text-red-600">{error}</p>}

            <label className="block text-sm">
              <span className="text-black/70">{copy.inviteFirstNameLabel}</span>
              <input
                className={fieldCls}
                value={firstName}
                placeholder={copy.inviteFirstNamePlaceholder}
                maxLength={60}
                onChange={(e) => setFirstName(e.target.value)}
              />
            </label>

            <label className="block text-sm">
              <span className="text-black/70">{copy.inviteBandLabel}</span>
              <select
                className={fieldCls}
                value={ageBand}
                onChange={(e) => setAgeBand(e.target.value)}
              >
                {AGE_BANDS.map((b) => (
                  <option key={b} value={b}>
                    {copy.ageBands[b] ?? b}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-sm">
              <span className="text-black/70">{copy.inviteLangLabel}</span>
              <select
                className={fieldCls}
                value={langCode}
                onChange={(e) => setLangCode(e.target.value)}
              >
                {LANG_CODES.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>

            <label className="block text-sm">
              <span className="text-black/70">{copy.inviteEmail}</span>
              <input
                type="email"
                className={fieldCls}
                value={parentEmail}
                maxLength={255}
                onChange={(e) => setParentEmail(e.target.value)}
              />
            </label>

            <label className="block text-sm">
              <span className="text-black/70">{copy.invitePinLabel}</span>
              <input
                className={fieldCls}
                value={pin}
                placeholder={copy.invitePinPlaceholder}
                maxLength={4}
                inputMode="numeric"
                onChange={(e) => setPin(e.target.value)}
              />
              {pinInvalid && <span className="mt-1 block text-xs text-red-600">{copy.invitePinInvalid}</span>}
            </label>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-black/10 px-3 py-2 text-sm text-black/60 hover:bg-black/5"
              >
                {copy.cancelBtn}
              </button>
              <button
                type="button"
                disabled={!canSubmit}
                onClick={() => void submit()}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {copy.inviteSendBtn}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
