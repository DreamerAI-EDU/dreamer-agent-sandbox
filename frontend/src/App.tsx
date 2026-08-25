import { useCallback, useEffect, useRef, useState } from 'react';
import { BAND_THEMES, MOCK_TURNS } from './lib/mock';
import type { ChatPayload, Lang } from './lib/mock';
import { createStream } from './lib/stream';
import { StageLoader, type ActiveStage } from './components/StageLoader';
import { AssistantMessage } from './components/ChatMessage';
import { Dibi } from './components/Dibi';
import { Starfield } from './components/Starfield';
import logoWhite from './assets/dreamer-logo-white.png';

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
    gateTitle: "Who's learning today?",
    gateName: 'Your nickname (optional)',
    gateStart: 'Start learning',
    bandDesc: ['Ages 6–8 · big steps, small words', 'Ages 9–11 · projects and why', 'Ages 12–14 · think deeper'],
    hi: (n: string) => `Hi, ${n}!`,
  },
  hk: {
    tagline: '問咩都得，用你嘅方法學。',
    placeholder: '喺度打你條問題…',
    send: '問 Dibi',
    disclaimer: 'Dreamer AI 有機會答錯——重要資訊記得同大人核實。',
    gateTitle: '今日邊個嚟學習呀？',
    gateName: '你嘅花名（填唔填都得）',
    gateStart: '開始學習',
    bandDesc: ['6–8 歲 · 多啲稱讚、淺白字', '9–11 歲 · 專題同「點解」', '12–14 歲 · 諗深一層'],
    hi: (n: string) => `${n}，你好呀！`,
  },
  cn: {
    tagline: '问什么都可以，用你的方式学。',
    placeholder: '在这里输入你的问题…',
    send: '问 Dibi',
    disclaimer: 'Dreamer AI 可能会答错——重要信息记得和大人核实。',
    gateTitle: '今天谁来学习呀？',
    gateName: '你的花名（可不填）',
    gateStart: '开始学习',
    bandDesc: ['6–8 岁 · 多称赞、浅白文字', '9–11 岁 · 专题和「为什么」', '12–14 岁 · 想深一层'],
    hi: (n: string) => `${n}，你好！`,
  },
};

interface CopyShape {
  tagline: string;
  placeholder: string;
  send: string;
  disclaimer: string;
  gateTitle: string;
  gateName: string;
  gateStart: string;
  bandDesc: readonly string[];
  hi: (n: string) => string;
}

// Stream seam: mock (VITE_BACKEND=mock, default) or future WS client
// implement the same StreamHandlers interface — see lib/stream.ts.
export default function App() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [bandIdx, setBandIdx] = useState(1);
  const [lang, setLang] = useState<Lang>('en');
  const [turns, setTurns] = useState<Turn[]>([]);
  const [stages, setStages] = useState<ActiveStage[] | null>(null);
  const [input, setInput] = useState('');
  const bottomRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  const theme = BAND_THEMES[profile?.bandIdx ?? bandIdx];
  const copy = COPY[lang];
  const busy = stages !== null;

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, stages]);

  useEffect(() => () => cancelRef.current?.(), []);

  const ask = useCallback(
    (text?: string) => {
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
    },
    [input, busy, theme.band, lang],
  );

  return (
    <div className="relative flex min-h-screen flex-col bg-[#1a1a2e] font-sans text-white">
      <Starfield />

      {/* Header — logo identical to dreamer-aiedu.net (white variant on navy) */}
      <header className="sticky top-0 z-10 border-b border-white/10 bg-[#1a1a2e]/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 py-3">
          <img src={logoWhite} alt="Dreamer AI Education" className="h-10 w-auto" />

          {profile?.name && (
            <p className="text-sm font-semibold text-white/80">{copy.hi(profile.name)}</p>
          )}

          <div className="ml-auto flex items-center gap-2">
            {profile && (
              <div
                className="flex rounded-full border border-white/15 bg-white/5 p-0.5"
                role="group"
                aria-label="Age band"
              >
                {BAND_THEMES.map((b, i) => {
                  const active = i === (profile.bandIdx ?? bandIdx);
                  return (
                    <button
                      key={b.band}
                      onClick={() => setProfile((p) => (p ? { ...p, bandIdx: i } : p))}
                      aria-pressed={active}
                      className={`rounded-full border px-3 py-1 text-xs font-bold transition-all duration-200 ${
                        active ? 'border-white/50 text-white' : 'border-transparent text-white/50 hover:text-white'
                      }`}
                      style={active ? { backgroundColor: `${b.accent}40` } : undefined}
                    >
                      {b.label}
                    </button>
                  );
                })}
              </div>
            )}
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
          </div>
        </div>
      </header>

      {profile === null ? (
        <Gate
          copy={copy}
          onStart={(p) => {
            setProfile(p);
            setBandIdx(p.bandIdx);
          }}
        />
      ) : (
        <>
          {/* Chat */}
          <main className="relative z-[1] mx-auto w-full max-w-3xl flex-1 px-4 py-6">
            <div className={theme.density}>
              {turns.length === 0 && (
                <div className="pt-10 text-center">
                  <div className="mx-auto w-fit animate-[wiggle_2.4s_ease-in-out_infinite]">
                    <Dibi size={62} accent={theme.accent} />
                  </div>
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
                  disabled={busy}
                  aria-label={copy.placeholder}
                  className="min-w-0 flex-1 rounded-full border border-white/15 bg-white/10 px-5 py-3 font-medium text-white outline-none placeholder:text-white/40 focus:border-white/40 disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={busy || !input.trim()}
                  className="shrink-0 rounded-full bg-[#6366f1] px-6 py-3 font-black text-white transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-40 disabled:hover:translate-y-0"
                  style={{ boxShadow: '0 0 18px #6366f166' }}
                >
                  {copy.send}
                </button>
              </form>
              <p className="mt-2 text-center text-[11px] text-white/40">{copy.disclaimer}</p>
            </div>
          </footer>
        </>
      )}
    </div>
  );
}

// First-run identity gate (answers "login first or next page?": identity FIRST,
// but kid-light — nickname + age band, no email. Real accounts arrive with W2.)
function Gate({
  copy,
  onStart,
}: {
  copy: CopyShape;
  onStart: (p: Profile) => void;
}) {
  const [name, setName] = useState('');
  const [picked, setPicked] = useState<number | null>(null);

  return (
    <main className="relative z-[1] mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center px-4 py-10 text-center">
      <div className="animate-[wiggle_2.4s_ease-in-out_infinite]">
        <Dibi size={62} accent="#83cef6" />
      </div>
      <h1 className="mt-5 text-3xl font-black tracking-tight text-white">{copy.gateTitle}</h1>

      <input
        value={name}
        onChange={(e) => setName(e.target.value.slice(0, 20))}
        placeholder={copy.gateName}
        aria-label={copy.gateName}
        className="mt-6 w-full max-w-xs rounded-full border border-white/15 bg-white/10 px-5 py-3 text-center font-medium text-white outline-none placeholder:text-white/40 focus:border-white/40"
      />

      <div className="mt-5 grid w-full max-w-md gap-3">
        {BAND_THEMES.map((b, i) => {
          const active = picked === i;
          return (
            <button
              key={b.band}
              onClick={() => setPicked(i)}
              aria-pressed={active}
              className={`rounded-2xl border-2 px-5 py-4 text-left transition-all duration-200 hover:-translate-y-0.5 ${
                active ? 'border-transparent' : 'border-white/15 bg-white/5 hover:border-white/35'
              }`}
              style={active ? { backgroundColor: `${b.accent}33`, borderColor: b.accent, boxShadow: `0 0 20px ${b.accent}44` } : undefined}
            >
              <span className="block text-lg font-black text-white">{b.label}</span>
              <span className="mt-0.5 block text-xs text-white/60">{copy.bandDesc[i]}</span>
            </button>
          );
        })}
      </div>

      <button
        onClick={() => picked !== null && onStart({ name: name.trim(), bandIdx: picked })}
        disabled={picked === null}
        className="mt-6 rounded-full bg-[#6366f1] px-8 py-3 font-black text-white transition-all hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-40 disabled:hover:translate-y-0"
        style={{ boxShadow: '0 0 18px #6366f166' }}
      >
        {copy.gateStart} →
      </button>
    </main>
  );
}
