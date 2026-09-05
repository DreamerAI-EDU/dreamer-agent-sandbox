// W2 PR#6 — chat page (kid experience). Mock demo + identity wiring.
// Phase 7 W3-A §4.2 — VITE_BACKEND=ws switches this page to the real WS chat
// stream (GET /api/ws/chat?student=<mask>, session cookie, same-origin). The
// mock stays reachable via VITE_BACKEND=mock|backend (single switch in
// lib/stream.ts). Real stream additions:
//   - content×N renders live through StreamingMessage (never just collected)
//   - connection tri-state UI + kid-safe error templates (raw errors → console)
//   - exponential-backoff reconnect with turn resume (subscribe_session tail)

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { BAND_THEMES, MOCK_TURNS } from '../lib/mock';
import type { ChatPayload, Lang } from '../lib/mock';
import { createStream, isRealWsMode } from '../lib/stream';
import type { ChatStreamStatus, KidErrorKind } from '../lib/chatErrors';
import { ERROR_COPY, RETRY_LABEL, STATUS_COPY } from '../lib/chatErrors';
import { StageLoader, type ActiveStage } from '../components/StageLoader';
import { AssistantMessage } from '../components/ChatMessage';
import { StreamingMessage } from '../components/StreamingMessage';
import { Dibi } from '../components/Dibi';
import { Starfield } from '../components/Starfield';
import logoWhite from '../assets/dreamer-logo-white.png';

const stream = createStream();
const realWs = isRealWsMode();

interface Turn {
  id: number;
  userText: string;
  payload?: ChatPayload;
  streamContent?: string; // live content×N accumulation (real WS)
}

interface Profile {
  name: string;
  bandIdx: number;
  student?: string; // 8-char mask from ?student=
}

const LANGS: { id: Lang; label: string }[] = [
  { id: 'en', label: 'EN' },
  { id: 'hk', label: '粵語' },
  { id: 'cn', label: '国语' },
];

const COPY = {
  en: {
    tagline: 'Ask anything. Learn your way.',
    placeholder: 'Type your question here…',
    send: 'Ask Dibi',
    disclaimer: 'Dreamer AI can make mistakes — check important info with a grown-up.',
    back: 'Back to children',
    hi: (n: string) => `Hi, ${n}!`,
    noProfile: 'Choose a child and enter the PIN to start chatting.',
  },
  hk: {
    tagline: '問咩都得，用你嘅方法學。',
    placeholder: '喺度打你條問題…',
    send: '問 Dibi',
    disclaimer: 'Dreamer AI 有機會答錯——重要資訊記得同大人核實。',
    back: '返回小朋友列表',
    hi: (n: string) => `${n}，你好呀！`,
    noProfile: '揀小朋友並輸入 PIN 先可以開始對話。',
  },
  cn: {
    tagline: '问什么都可以，用你的方式学。',
    placeholder: '在这里输入你的问题…',
    send: '问 Dibi',
    disclaimer: 'Dreamer AI 可能会答错——重要信息记得和大人核实。',
    back: '返回孩子列表',
    hi: (n: string) => `${n}，你好！`,
    noProfile: '选择孩子并输入 PIN 才能开始对话。',
  },
};

// Banner tone per error class — layered so auth vs permission vs network
// reads differently to the grown-up who is standing behind the kid.
function bannerTone(kind: KidErrorKind): 'auth' | 'permission' | 'soft' {
  if (kind === 'auth') return 'auth';
  if (kind === 'permission' || kind === 'no-student') return 'permission';
  return 'soft';
}

const TONE_STYLE: Record<'auth' | 'permission' | 'soft', { bg: string; border: string; dot: string }> = {
  auth: { bg: 'rgba(248,113,113,0.12)', border: 'rgba(248,113,113,0.45)', dot: '#f87171' },
  permission: { bg: 'rgba(251,191,36,0.10)', border: 'rgba(251,191,36,0.4)', dot: '#fbbf24' },
  soft: { bg: 'rgba(131,206,246,0.10)', border: 'rgba(131,206,246,0.35)', dot: '#83cef6' },
};

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const rawName = searchParams.get('name') ?? '';
  const rawStudent = searchParams.get('student') ?? '';
  const band = searchParams.get('band') ?? 'P4-P6';
  const bandIdx = Math.max(0, BAND_THEMES.findIndex((b) => b.band === band));
  const profile: Profile = { name: rawName, bandIdx, student: realWs ? rawStudent : undefined };

  const [lang, setLang] = useState<Lang>('en');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stages, setStages] = useState<ActiveStage[] | null>(null);
  const [progressNote, setProgressNote] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [wsStatus, setWsStatus] = useState<ChatStreamStatus | 'idle'>('idle');
  const [kidError, setKidError] = useState<KidErrorKind | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const lastQuestionRef = useRef('');
  const idRef = useRef(0);

  const theme = BAND_THEMES[profile.bandIdx];
  const copy = COPY[lang];
  const err = kidError ? ERROR_COPY[kidError] : null;

  const activeStreaming =
    wsStatus === 'connecting' || wsStatus === 'streaming' || wsStatus === 'disconnected' || wsStatus === 'reconnecting';
  const busy = stages !== null || activeStreaming;
  const blockedByError = kidError === 'auth' || kidError === 'permission' || kidError === 'no-student';
  const inputDisabled = busy || !profile.name || blockedByError;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, stages, wsStatus]);

  // Unmount cleanup: close the socket, clear backoff timers.
  useEffect(() => () => cancelRef.current?.(), []);

  const ask = (text?: string) => {
    const userText = (text ?? input).trim();
    if (!userText || busy || !profile.name) return;
    cancelRef.current?.(); // clear any previous stream before opening a new one
    setInput('');
    setStages([]);
    setProgressNote(null);
    setKidError(null);
    setWsStatus(realWs ? 'connecting' : 'idle');
    lastQuestionRef.current = userText;
    const id = ++idRef.current;
    setTurns((t) => [...t, { id, userText }]);
    cancelRef.current = stream(
      userText,
      theme.band,
      lang,
      {
        onStages: setStages,
        onProgress: () => {},
        onProgressNote: (note) => setProgressNote(note),
        onContent: (chunk) => {
          // True streaming render: content×N appends to the live bubble.
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, streamContent: (x.streamContent ?? '') + chunk } : x)));
        },
        onResult: (payload) => {
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, payload, streamContent: undefined } : x)));
          setStages(null);
          setProgressNote(null);
        },
        onStatus: (status) => {
          setWsStatus(status);
          if (status === 'idle') {
            // turn fully terminal — nothing in flight
            setStages(null);
            setProgressNote(null);
          }
        },
        onError: (kind) => {
          setKidError(kind);
          setWsStatus('failed');
        },
      },
      { student: profile.student },
    );
  };

  const retryLast = () => {
    if (lastQuestionRef.current) ask(lastQuestionRef.current);
  };

  return (
    <div className="relative flex min-h-screen flex-col bg-[#1a1a2e] font-sans text-white">
      <Starfield />

      {/* Header — logo identical to dreamer-aiedu.net (white variant on navy) */}
      <header className="sticky top-0 z-10 border-b border-white/10 bg-[#1a1a2e]/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 py-3">
          <img src={logoWhite} alt="Dreamer AI Education" className="h-10 w-auto" />

          {profile.name && <p className="text-sm font-semibold text-white/80">{copy.hi(profile.name)}</p>}

          <div className="ml-auto flex items-center gap-2">
            <div
              className="flex rounded-full border border-white/15 bg-white/5 p-0.5"
              role="group"
              aria-label="Age band"
            >
              {BAND_THEMES.map((b, i) => {
                const active = i === profile.bandIdx;
                return (
                  <button
                    key={b.band}
                    aria-pressed={active}
                    className={`rounded-full border px-3 py-1 text-xs font-bold transition-all duration-200 ${
                      active ? 'border-white/50 text-white' : 'border-transparent text-white/50'
                    }`}
                    style={active ? { backgroundColor: `${b.accent}40` } : undefined}
                  >
                    {b.label}
                  </button>
                );
              })}
            </div>
            <div
              className="flex rounded-full border border-white/15 bg-white/5 p-0.5"
              role="group"
              aria-label="Language"
            >
              {LANGS.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setLang(l.id)}
                  aria-pressed={lang === l.id}
                  className={`rounded-full px-2.5 py-1 text-xs font-bold transition-colors ${
                    lang === l.id ? 'bg-white text-[#1a1a2e]' : 'text-white/50 hover:text-white'
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
            <Link
              to="/home"
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white/80 hover:text-white"
            >
              {copy.back}
            </Link>
          </div>
        </div>
      </header>

      {/* Chat */}
      <main className="relative z-[1] mx-auto w-full max-w-3xl flex-1 px-4 py-6">
        <div className={theme.density}>
          {turns.length === 0 && (
            <div className="pt-10 text-center">
              <div className="mx-auto w-fit animate-[wiggle_2.4s_ease-in-out_infinite]">
                <Dibi size={62} accent={theme.accent} />
              </div>
              {profile.name ? (
                <>
                  <h1 className="mt-5 text-3xl font-black tracking-tight text-white">{copy.tagline}</h1>
                  {!realWs && (
                    <div className="mt-6 flex flex-col items-center gap-2.5">
                      {MOCK_TURNS.map((t, i) => (
                        <button
                          key={i}
                          onClick={() => ask(t.user[lang])}
                          className="rounded-full border border-white/20 bg-white/5 px-5 py-2.5 text-sm font-semibold text-white transition-all hover:-translate-y-0.5 hover:border-white/50 active:translate-y-0"
                        >
                          {t.user[lang]}
                        </button>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <p className="mt-5 text-lg font-semibold text-white/70">{copy.noProfile}</p>
              )}
            </div>
          )}

          {turns.map((turn) => (
            <div key={turn.id} className={theme.density}>
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-3xl rounded-br-md bg-[#6366f1] px-5 py-3 font-semibold text-white">
                  {turn.userText}
                </div>
              </div>
              {turn.payload ? (
                <AssistantMessage payload={turn.payload} theme={theme} lang={lang} />
              ) : turn.streamContent ? (
                <StreamingMessage content={turn.streamContent} theme={theme} />
              ) : (
                stages !== null && <StageLoader stages={stages} theme={theme} lang={lang} note={progressNote} />
              )}
            </div>
          ))}

          {/* Connection / error banner — lives at the bottom of the flow so
              children see it without it covering the send bar. */}
          {wsStatus === 'disconnected' && (
            <ConnectionPill text={STATUS_COPY.disconnected[lang]} tone="soft" />
          )}
          {wsStatus === 'reconnecting' && (
            <ConnectionPill text={STATUS_COPY.reconnecting[lang]} tone="soft" />
          )}
          {wsStatus === 'failed' && err && (
            <ErrorBanner
              kind={kidError as KidErrorKind}
              title={err.title[lang]}
              hint={err.hint[lang]}
              lang={lang}
              canRetry={
                kidError === 'network' || kidError === 'upstream' || kidError === 'turn-lost'
              }
              onRetry={retryLast}
            />
          )}
          <div ref={bottomRef} />
        </div>
      </main>

      {/* Input */}
      <footer className="sticky bottom-0 z-10 border-t border-white/10 bg-[#1a1a2e]/90 backdrop-blur">
        <div className="mx-auto max-w-3xl px-4 py-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask();
            }}
            className="flex gap-2"
          >
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={copy.placeholder}
              disabled={inputDisabled}
              aria-label={copy.placeholder}
              className="min-w-0 flex-1 rounded-full border border-white/15 bg-white/10 px-5 py-3 font-medium text-white outline-none placeholder:text-white/40 focus:border-white/40 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={inputDisabled || !input.trim()}
              className="shrink-0 rounded-full bg-[#6366f1] px-6 py-3 font-black text-white transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-40 disabled:hover:translate-y-0"
              style={{ boxShadow: '0 0 18px #6366f166' }}
            >
              {copy.send}
            </button>
          </form>
          <p className="mt-2 text-center text-[11px] text-white/40">{copy.disclaimer}</p>
        </div>
      </footer>
    </div>
  );
}

function ConnectionPill({ text, tone }: { text: string; tone: 'soft' | 'auth' | 'permission' }) {
  const s = TONE_STYLE[tone];
  return (
    <div
      className="flex items-center justify-center gap-2 rounded-full border px-4 py-2 text-sm font-semibold"
      style={{ backgroundColor: s.bg, borderColor: s.border }}
      role="status"
      aria-live="polite"
    >
      <span className="h-2 w-2 animate-pulse rounded-full" style={{ backgroundColor: s.dot }} aria-hidden />
      {text}
    </div>
  );
}

function ErrorBanner({
  kind,
  title,
  hint,
  lang,
  canRetry,
  onRetry,
}: {
  kind: KidErrorKind;
  title: string;
  hint: string;
  lang: Lang;
  canRetry: boolean;
  onRetry: () => void;
}) {
  const s = TONE_STYLE[bannerTone(kind)];
  return (
    <div
      className="flex flex-col items-center gap-2 rounded-3xl border px-5 py-4 text-center"
      style={{ backgroundColor: s.bg, borderColor: s.border }}
      role="alert"
    >
      <p className="text-sm font-bold text-white">{title}</p>
      {hint && <p className="text-xs text-white/70">{hint}</p>}
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 rounded-full border border-white/40 bg-white/10 px-5 py-1.5 text-xs font-bold text-white transition-colors hover:bg-white/20"
        >
          {RETRY_LABEL[lang]}
        </button>
      )}
    </div>
  );
}
