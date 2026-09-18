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
import { hasInflightTurn } from '../lib/chatWs';
import type { ChatStreamStatus, KidErrorKind } from '../lib/chatErrors';
import { ERROR_COPY, RETRY_LABEL, STATUS_COPY, STOP_LABEL } from '../lib/chatErrors';
import { StageLoader, type ActiveStage } from '../components/StageLoader';
import { AssistantMessage } from '../components/ChatMessage';
import { StreamingMessage } from '../components/StreamingMessage';
import { Dibi } from '../components/Dibi';
import { Starfield } from '../components/Starfield';
import { WelcomeBubble } from '../components/WelcomeBubble';
import { useLang } from '../lib/i18n';
import { ApiError, api } from '../lib/api';
import type { StudentCurriculumResponse } from '../lib/types';
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
    backStudent: 'Back to my space',
    gallery: 'My Gallery',
    hi: (n: string) => `Hi, ${n}!`,
    noProfile: 'Choose a child and enter the PIN to start chatting.',
    // PR-B — first-visit welcome bubble. Personalised only when BOTH the
    // student first name and a live week_index exist; every other path
    // (no name / empty / failed curriculum) collapses to the plain line and
    // never renders a mask or error surface.
    welcomePersonal: (n: string, w: number, p: number) =>
      `Hi ${n}! You're on Week ${w} — ${p}% of your course done. Ask me anything about today's lesson!`,
    welcomeFallback: "Welcome! Ask me anything — I'm here to help you learn.",
  },
  hk: {
    tagline: '問咩都得，用你嘅方法學。',
    placeholder: '喺度打你條問題…',
    send: '問 Dibi',
    disclaimer: 'Dreamer AI 有機會答錯——重要資訊記得同大人核實。',
    back: '返回小朋友列表',
    backStudent: '返去我嘅空間',
    gallery: '我嘅作品展',
    hi: (n: string) => `${n}，你好呀！`,
    noProfile: '揀小朋友並輸入 PIN 先可以開始對話。',
    // PR-B — first-visit welcome bubble (zh-hk 用粵語，跟 PR-0 lang mapping)。
    welcomePersonal: (n: string, w: number, p: number) =>
      `${n}，你好呀！你而家喺第 ${w} 週，課程完成咗 ${p}%。今日有咩想問 Dibi？`,
    welcomeFallback: '歡迎你！有咩想知、想問，都可以同 Dibi 傾。',
  },
  cn: {
    tagline: '问什么都可以，用你的方式学。',
    placeholder: '在这里输入你的问题…',
    send: '问 Dibi',
    disclaimer: 'Dreamer AI 可能会答错——重要信息记得和大人核实。',
    back: '返回孩子列表',
    backStudent: '返回我的空间',
    gallery: '我的作品展',
    hi: (n: string) => `${n}，你好！`,
    noProfile: '选择孩子并输入 PIN 才能开始对话。',
    // PR-B — first-visit welcome bubble.
    welcomePersonal: (n: string, w: number, p: number) =>
      `${n}，你好！你现在在第 ${w} 周，课程已完成 ${p}%。今天有什么想问 Dibi 吗？`,
    welcomeFallback: '欢迎你！有什么想知道的、想问的，都可以和 Dibi 聊。',
  },
};

// Mount-resume placeholder — rendered as the userText of the turn bubble
// created when a fresh page-load found a still-running turn. The WS then
// either replays the tail (resume) or collapses to the gentle resume-lost
// banner (session_closed) — the kid never sees an empty bubble.
const RESUME_PLACEHOLDER: Record<Lang, string> = {
  en: 'You were in the middle of a question — Dibi is catching up…',
  hk: '你頭先問緊問題——Dibi 正在追返個答案…',
  cn: '你刚才问了个问题——Dibi 正在追回答案…',
};

// Bridge-3a — "Week X / 8" badge chrome (chat top bar). Only this frame is
// localized client-side; the unit title always comes from the backend
// (topic_metadata, label_soften tradition) and is rendered verbatim — the
// frontend never translates an internal topic_id (North Star #3).
const WEEK_COPY: Record<Lang, { week: (n: number, t: number) => string; done: (t: number) => string }> = {
  en: {
    week: (n, t) => `Week ${n} / ${t}`,
    done: (t) => `${t}/${t} · Complete`,
  },
  hk: {
    week: (n, t) => `第 ${n} 週 / ${t}`,
    done: (t) => `${t}/${t} · 完成`,
  },
  cn: {
    week: (n, t) => `第 ${n} 周 / ${t}`,
    done: (t) => `${t}/${t} · 完成`,
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
  const fromStudent = searchParams.get('from') === 'student';
  const bandIdx = Math.max(0, BAND_THEMES.findIndex((b) => b.band === band));
  const profile: Profile = { name: rawName, bandIdx, student: realWs ? rawStudent : undefined };

  // PR-0 i18n: the student's saved lang_code drives the page language — the
  // console (StudentHomePage) maps zh-hk/zh-cn/en into the global provider,
  // so the bubble inherits that same mapping instead of defaulting to EN.
  const { lang: uiLang } = useLang();
  const [lang, setLang] = useState<Lang>(uiLang === 'hk' ? 'hk' : uiLang === 'cn' ? 'cn' : 'en');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stages, setStages] = useState<ActiveStage[] | null>(null);
  const [progressNote, setProgressNote] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [wsStatus, setWsStatus] = useState<ChatStreamStatus | 'idle'>('idle');
  const [kidError, setKidError] = useState<KidErrorKind | null>(null);
  const [curriculum, setCurriculum] = useState<{ for: string; data: StudentCurriculumResponse } | null>(
    null,
  );
  const [welcomeText, setWelcomeText] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  const lastQuestionRef = useRef('');
  const idRef = useRef(0);

  const theme = BAND_THEMES[profile.bandIdx];
  const copy = COPY[lang];
  const err = kidError ? ERROR_COPY[kidError] : null;

  // Bridge-3a — top-bar badge text. 'none' / a missing week index / any load
  // failure all collapse to `null`: the badge is simply hidden (the backend
  // already answers a neutral 200, so a child never sees an error here).
  const weekCopy = WEEK_COPY[lang];
  const curriculumData =
    curriculum && curriculum.for === profile.student ? curriculum.data : null;
  let weekBadge: { text: string; unit: string } | null = null;
  if (curriculumData?.state === 'completed') {
    weekBadge = { text: weekCopy.done(curriculumData.total_weeks), unit: curriculumData.unit_title };
  } else if (curriculumData?.state === 'active' && curriculumData.week_index !== null) {
    weekBadge = {
      text: weekCopy.week(curriculumData.week_index, curriculumData.total_weeks),
      unit: curriculumData.unit_title,
    };
  }

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

  // Bridge-3a — kid "Week X / 8" badge. Loaded on mount and re-read when the
  // tab regains focus (a teacher's advance-week shows up without a reload);
  // re-reads stop on unmount. Silent on failure by design. The response is
  // tagged with the identifier it was fetched for, so a stale payload can
  // never paint for a different child.
  useEffect(() => {
    const identifier = profile.student;
    if (!realWs || !identifier) return; // no tag → the derived badge stays null
    let alive = true;
    const load = () => {
      api.studentCurriculum(identifier).then(
        (resp) => {
          if (alive) setCurriculum({ for: identifier, data: resp });
        },
        (e: unknown) => {
          if (alive) setCurriculum(null);
          // 401/403/400 are expected states, not bugs — stay quiet for those.
          if (!(e instanceof ApiError)) console.warn('Week badge unavailable', e);
        },
      );
    };
    load();
    const onFocus = () => load();
    window.addEventListener('focus', onFocus);
    return () => {
      alive = false;
      window.removeEventListener('focus', onFocus);
    };
  }, [profile.student]);

  // PR-B — first-visit welcome bubble above the input on the empty chat
  // state. Trigger is ChatPage mount + empty turns + per-mask flag unset —
  // zero WS coupling (no handshake dependency) and never on top of a chat
  // history. Data comes from the authenticated /api/student/me body, NOT the
  // URL: first_name + week_index arrive over the wire (no PII in query
  // strings / access logs) and client-supplied URL params are ignored
  // (red line 7). Personalised ONLY when BOTH first_name and a live
  // week_index exist (pct = round(week/8*100), fixed definition); any
  // failure (no name / 200 empty / 500 / 403 / timeout) collapses to the
  // plain welcome line, which never renders a mask. The flag is marked the
  // moment the bubble is about to render, not on close.
  useEffect(() => {
    const mask = profile.student;
    if (!realWs || !mask) return;
    if (turns.length > 0) return;
    const KEY = `welcome_shown_v1_${mask}`;
    try {
      if (window.localStorage.getItem(KEY)) return;
    } catch {
      // storage unavailable — still show the bubble for this mount
    }
    let alive = true;
    api.studentMe().then(
      (resp) => {
        if (!alive) return;
        const name = resp.student?.first_name?.trim() ?? '';
        const w = resp.badge?.week_index ?? null;
        const total = resp.badge?.total_weeks ?? 0;
        if (name && w !== null && total > 0) {
          setWelcomeText(copy.welcomePersonal(name, w, Math.round((w / 8) * 100)));
        } else {
          setWelcomeText(copy.welcomeFallback);
        }
      },
      () => {
        if (alive) setWelcomeText(copy.welcomeFallback);
      },
    );
    return () => {
      alive = false;
    };
  }, [profile.student, turns.length, copy]);

  // Mark the per-mask flag the moment the bubble renders.
  useEffect(() => {
    if (welcomeText === null) return;
    const mask = profile.student;
    if (!realWs || !mask) return;
    try {
      window.localStorage.setItem(`welcome_shown_v1_${mask}`, '1');
    } catch {
      // ignore persistence failures
    }
  }, [welcomeText, profile.student]);

  // Mount-resume (PR-C item 2 gap fix): a fresh page-load that finds a turn
  // still in flight (sessionStorage marker left by the pre-reload page) opens
  // a silent WS stream with an EMPTY question — the relay replays the tail,
  // or answers session_closed which this stream reports as the gentle
  // resume-lost banner (resumeFromMount), NOT the quiet finish reserved for
  // same-instance reconnects. Never fires when turns already exist (the user
  // is mid-session this mount) or when the marker is absent.
  useEffect(() => {
    const mask = profile.student;
    if (!realWs || !mask) return;
    if (!hasInflightTurn(mask)) return;
    if (turns.length > 0) return;
    cancelRef.current?.();
    setWsStatus('connecting');
    cancelRef.current = stream(
      '',
      theme.band,
      lang,
      {
        onStages: setStages,
        onProgress: () => {},
        onProgressNote: (note) => setProgressNote(note),
        onContent: (chunk) => {
          setTurns((t) => {
            if (t.length === 0) {
              const id = ++idRef.current;
              return [{ id, userText: RESUME_PLACEHOLDER[lang], streamContent: chunk }];
            }
            const last = t[t.length - 1];
            return t.map((x) =>
              x.id === last.id ? { ...x, streamContent: (x.streamContent ?? '') + chunk } : x,
            );
          });
        },
        onResult: (payload) => {
          setTurns((t) => {
            if (t.length === 0) {
              const id = ++idRef.current;
              return [{ id, userText: RESUME_PLACEHOLDER[lang], payload }];
            }
            const last = t[t.length - 1];
            return t.map((x) => (x.id === last.id ? { ...x, payload, streamContent: undefined } : x));
          });
          setStages(null);
          setProgressNote(null);
        },
        onStatus: (status) => {
          setWsStatus(status);
          if (status === 'idle') {
            setStages(null);
            setProgressNote(null);
          }
        },
        onError: (kind) => {
          setKidError(kind);
          setWsStatus('failed');
        },
      },
      { student: mask, resumeFromMount: true },
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profile.student]);

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

  // P4 §4.1(9) — Stop button: end the in-flight turn on the child's terms.
  // Closing the stream lets the server reap the turn (client_closed) and the
  // persisted engine session stays put, so the NEXT question resumes the
  // same session instead of opening a fresh one (§4.1(8) reuse).
  const stop = () => {
    cancelRef.current?.();
    setWsStatus('idle');
    setStages(null);
    setProgressNote(null);
  };

  // Gallery deep link keeps the chat session context (mask / name / band).
  // Only reachable in real WS mode where a PIN-unlocked student exists; the
  // mock demo has no real portfolio backend behind it.
  const galleryUrl = profile.student
    ? `/portfolio?student=${encodeURIComponent(profile.student)}&name=${encodeURIComponent(
        profile.name || '',
      )}&band=${encodeURIComponent(theme.band)}`
    : null;

  return (
    <div className="relative flex min-h-screen flex-col bg-[#1a1a2e] font-sans text-white">
      <Starfield />

      {/* Header — logo identical to dreamer-aiedu.net (white variant on navy) */}
      <header className="sticky top-0 z-10 border-b border-white/10 bg-[#1a1a2e]/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 py-3">
          <img src={logoWhite} alt="Dreamer AI Education" className="h-10 w-auto" />

          {profile.name && <p className="text-sm font-semibold text-white/80">{copy.hi(profile.name)}</p>}

          {/* Bridge-3a — "Week X / 8" badge. Week frame is localized here,
              the unit title is backend text rendered verbatim. */}
          {weekBadge && (
            <div
              className="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold text-white/90"
              style={{ borderColor: `${theme.accent}66`, backgroundColor: `${theme.accent}1f` }}
              title={weekBadge.unit || undefined}
            >
              <span>{weekBadge.text}</span>
              {weekBadge.unit && (
                <span className="hidden max-w-[16rem] truncate font-semibold text-white/60 sm:inline">
                  · {weekBadge.unit}
                </span>
              )}
            </div>
          )}

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
            {galleryUrl && (
              <Link
                to={galleryUrl}
                className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white/80 hover:text-white"
              >
                {copy.gallery}
              </Link>
            )}
            <Link
              to={fromStudent ? '/student' : '/home'}
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white/80 hover:text-white"
            >
              {fromStudent ? copy.backStudent : copy.back}
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

              {/* PR-B — first-visit welcome bubble. Sits below the tagline on
                  the empty chat state (real-WS students only); the text is
                  already localised and masked-safe by the effect above. The
                  turns guard covers the race where the student starts
                  chatting before the fetch resolves. */}
              {turns.length === 0 && welcomeText && (
                <WelcomeBubble text={welcomeText} accent={theme.accent} />
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
            {activeStreaming && (
              <button
                type="button"
                onClick={stop}
                aria-label={STOP_LABEL[lang]}
                className="shrink-0 rounded-full border border-white/25 bg-white/10 px-5 py-3 font-black text-white transition-colors hover:bg-white/20"
              >
                {STOP_LABEL[lang]}
              </button>
            )}
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
