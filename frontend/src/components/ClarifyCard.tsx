// PR-D-b2 — clarify card (design v0.2.1 §3, B.1–B.4).
//
// The engine can pause a turn to ask the kid a clarifying question
// (upstream `tool_call` / `ask_user`). This component renders that question
// as a card in the flow, driven by a one-way state machine:
//
//   waiting ──kid picks──> selected ──engine content──> removed
//      └────relay clarify timeout────> timeout ──> removed (banner takes over)
//
// Design rules honoured here:
//   - the card NEVER generates or trims options — the engine payload is the
//     single source of truth (§B.2); `band` only drives chrome (size/layout)
//   - copy follows Q5 (no #, no * , no "- " list markers, no tables, no code
//     fences) and locale D1 (zh-hk ⇒ Cantonese colloquial)
//   - the card NEVER counts down on its own: timeout is decided by the relay
//     alone (§B.3 single-clock rule) and arrives as an `error` frame, which
//     the page turns into `status="timeout"`
//   - `waiting` / `timeout` both leave the composer usable — a failed or
//     timed-out card must never lock the kid out of typing

import type { Lang } from '../lib/mock';

/** Wire band ids (§A.2 F1) — lowercase, as sent by the engine / relay. */
export type ClarifyBand = 's1-s3' | 'p1-p3' | 'p4-p6';

export type ClarifyOption = { id: string; label: string };

/** One-way state machine (§B.1): waiting → selected | timeout. Never reversed. */
export type ClarifyStatus = 'waiting' | 'selected' | 'timeout';

export interface ClarifyCardProps {
  /** Engine-owned id (§A.2) — also the render de-dup key (replay safe). */
  toolCallId: string;
  question?: string;
  options: ClarifyOption[];
  band: ClarifyBand;
  status: ClarifyStatus;
  selected?: string[];
  /** Engine flag (§A.2 `tool_args.allow_free_text`) — hint only: the free-text
   *  path is the page composer, never a field inside the card. */
  allowFreeText?: boolean;
  lang: Lang;
  onSelect: (ids: string[]) => void;
}

// Card-local copy. Kept next to the component (not in chatErrors.ts, which
// owns connection/error wording) — same Q5 / locale-D1 constraints apply.
const CARD_COPY: Record<Lang, { freeTextHint: string; selected: string; timeout: string }> = {
  en: {
    freeTextHint: 'Or just type your question.',
    selected: 'Got it. Dibi is answering…',
    timeout: 'This card has timed out. You can just type your question again.',
  },
  hk: {
    freeTextHint: '或者直接打字講。',
    selected: '收到，等 Dibi 答你…',
    timeout: '呢張卡已經逾時，你可以直接打字再講一次。',
  },
  cn: {
    freeTextHint: '或者直接打字说。',
    selected: '收到，等 Dibi 回答…',
    timeout: '这张卡已经超时，你可以直接打字再说一次。',
  },
};

// Band chrome only (§B.2): s1-s3 gets the largest type and the widest spacing,
// p4-p6 may lay options out in two columns on wider screens.
const BAND_CHROME: Record<ClarifyBand, { list: string; option: string; question: string }> = {
  's1-s3': {
    list: 'flex flex-col gap-3',
    option: 'rounded-2xl px-6 py-4 text-lg',
    question: 'text-xl',
  },
  'p1-p3': {
    list: 'flex flex-col gap-2.5',
    option: 'rounded-2xl px-5 py-3 text-base',
    question: 'text-lg',
  },
  'p4-p6': {
    list: 'grid grid-cols-1 gap-2.5 sm:grid-cols-2',
    option: 'rounded-2xl px-5 py-3 text-base',
    question: 'text-lg',
  },
};

export function ClarifyCard({
  toolCallId,
  question,
  options,
  band,
  status,
  selected,
  allowFreeText,
  lang,
  onSelect,
}: ClarifyCardProps) {
  const copy = CARD_COPY[lang];
  const chrome = BAND_CHROME[band];
  const locked = status !== 'waiting';
  const picked = selected ?? [];

  return (
    <div
      className="rounded-3xl border border-white/15 bg-white/5 px-4 py-4"
      data-tool-call-id={toolCallId}
      role="group"
      aria-label={question || undefined}
    >
      {question && <p className={`font-bold text-white ${chrome.question}`}>{question}</p>}

      {options.length > 0 && (
        <div className={`${chrome.list}${question ? ' mt-3' : ''}`}>
          {options.map((o) => {
            const isPicked = picked.includes(o.id);
            return (
              <button
                key={o.id}
                type="button"
                disabled={locked}
                aria-pressed={isPicked}
                onClick={() => onSelect([o.id])}
                className={`border font-semibold text-white transition-all duration-200 ${
                  isPicked
                    ? 'border-white/60 bg-white/20'
                    : 'border-white/20 bg-white/5 hover:border-white/50'
                } ${
                  locked ? 'cursor-default opacity-60' : 'hover:-translate-y-0.5 active:translate-y-0'
                } ${chrome.option}`}
              >
                {o.label}
              </button>
            );
          })}
        </div>
      )}

      {status === 'waiting' && allowFreeText && (
        <p className="mt-3 text-xs text-white/60">{copy.freeTextHint}</p>
      )}
      {status === 'selected' && (
        <p className="mt-3 text-xs text-white/60" role="status" aria-live="polite">
          {copy.selected}
        </p>
      )}
      {status === 'timeout' && <p className="mt-3 text-xs text-white/60">{copy.timeout}</p>}
    </div>
  );
}
