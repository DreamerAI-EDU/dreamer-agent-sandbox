// W2 PR#6 — chat page (kid experience).
// CHAT MOCK KEPT INTENTIONALLY: this page still drives the scripted
// MOCK_TURNS + stream seam (VITE_BACKEND=mock|ws). The real WS stream is
// handed over to W3 — this PR only wires identity: the parent selects a
// child and unlocks with PIN on /home, then lands here with the child's
// mask prefix + band via query params. Full student ids are never used.

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { BAND_THEMES, MOCK_TURNS } from '../lib/mock';
import type { ChatPayload, Lang } from '../lib/mock';
import { createStream } from '../lib/stream';
import { StageLoader, type ActiveStage } from '../components/StageLoader';
import { AssistantMessage } from '../components/ChatMessage';
import { Dibi } from '../components/Dibi';
import { Starfield } from '../components/Starfield';
import logoWhite from '../assets/dreamer-logo-white.png';

const stream = createStream();

interface Turn {
  id: number;
  userText: string;
  payload?: ChatPayload;
}

interface Profile {
  name: string;
  bandIdx: number;
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

export default function ChatPage() {
  const [searchParams] = useSearchParams();
  const rawName = searchParams.get('name') ?? '';
  const band = searchParams.get('band') ?? 'P4-P6';
  const bandIdx = Math.max(0, BAND_THEMES.findIndex((b) => b.band === band));
  const profile: Profile = { name: rawName, bandIdx };

  const [lang, setLang] = useState<Lang>('en');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stages, setStages] = useState<ActiveStage[] | null>(null);
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const theme = BAND_THEMES[profile.bandIdx];
  const copy = COPY[lang];
  const busy = stages !== null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, stages]);

  useEffect(() => () => cancelRef.current?.(), []);

  const ask = (text?: string) => {
    const userText = (text ?? input).trim();
    if (!userText || busy) return;
    setInput('');
    const id = Date.now();
    setTurns((t) => [...t, { id, userText }]);
    setStages([]);
    cancelRef.current = stream(
      userText,
      theme.band,
      lang,
      {
        onStages: setStages,
        onProgress: () => {},
        onContent: () => {},
        onResult: (payload) => {
          setTurns((t) => t.map((x) => (x.id === id ? { ...x, payload } : x)));
          setStages(null);
        },
      },
    );
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
              ) : (
                stages && <StageLoader stages={stages} theme={theme} lang={lang} />
              )}
            </div>
          ))}
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
              disabled={busy || !profile.name}
              aria-label={copy.placeholder}
              className="min-w-0 flex-1 rounded-full border border-white/15 bg-white/10 px-5 py-3 font-medium text-white outline-none placeholder:text-white/40 focus:border-white/40 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={busy || !input.trim() || !profile.name}
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
