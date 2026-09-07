// W4 PR-B Step 2 — kid-facing portfolio page (/portfolio).
//
// Opened from the chat header with the same query the chat page carries:
//   /portfolio?student=<mask>&name=<first name>&band=P1-P3|P4-P6|S1-S3
// Data comes from GET /api/student/portfolio?student=<mask> — the kid
// surface NEVER carries share_cards and this page must have NO share
// affordance anywhere (R2): no visible button, no hover menu, no long-press
// menu.
//
// 4D badge values come from the backend competencies_4d array and are
// rendered verbatim (R5 — no client-side label translation). growth_note /
// kid_label / title / description are backend text rendered as-is.
//
// Band-aware rendering: P1–P3 gets larger type and a single-card rhythm;
// P4–P6 / S1–S3 use the tighter grid. Empty state is kid-facing welcome
// copy (the parent empty state lives on /parent · view=portfolio).

import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router';
import { BAND_THEMES } from '../lib/mock';
import type { Lang } from '../lib/mock';
import { api } from '../lib/api';
import type { PortfolioItem } from '../lib/portfolioTypes';
import { Starfield } from '../components/Starfield';
import { Badge4D } from '../components/portfolio/Badge4D';
import logoWhite from '../assets/dreamer-logo-white.png';

const LANGS: { id: Lang; label: string }[] = [
  { id: 'en', label: 'EN' },
  { id: 'hk', label: '粵語' },
  { id: 'cn', label: '国语' },
];

const COPY = {
  en: {
    gallery: 'My Gallery',
    sub: (n: string) => `${n}'s creations`,
    emptyTitle: 'Your gallery is waiting for its first creation!',
    emptyHint: 'Finish a challenge with Dibi and your work will show up here.',
    noStudent: 'Choose a child and enter the PIN to see their gallery.',
    loading: 'Loading your gallery…',
    loadError: 'Something went wrong while loading your gallery.',
    back: 'Back to chat',
    dateLabel: 'Made on',
    skillLabel: 'Skills I practised',
    tryAgain: 'Try again',
  },
  hk: {
    gallery: '我嘅作品展',
    sub: (n: string) => `${n} 嘅創作`,
    emptyTitle: '你嘅作品展等緊第一個作品！',
    emptyHint: '同 Dibi 完成一個挑戰，你嘅作品就會喺度出現。',
    noStudent: '揀小朋友並輸入 PIN 先可以睇佢嘅作品展。',
    loading: '載入緊你嘅作品展…',
    loadError: '載入作品展嗰陣發生咗問題。',
    back: '返回對話',
    dateLabel: '完成日期',
    skillLabel: '我練習嘅技能',
    tryAgain: '再試一次',
  },
  cn: {
    gallery: '我的作品展',
    sub: (n: string) => `${n} 的创作`,
    emptyTitle: '你的作品展在等第一个作品！',
    emptyHint: '和 Dibi 一起完成一个挑战，你的作品就会出现在这里。',
    noStudent: '选择孩子并输入 PIN 才能查看 ta 的作品展。',
    loading: '正在加载你的作品展…',
    loadError: '加载作品展时出了点问题。',
    back: '返回对话',
    dateLabel: '完成日期',
    skillLabel: '我练习的技能',
    tryAgain: '再试一次',
  },
};

interface KidProfile {
  name: string;
  band: string;
  student: string;
}

export default function KidPortfolioPage() {
  const [searchParams] = useSearchParams();
  const rawStudent = (searchParams.get('student') ?? '').trim();
  const rawName = (searchParams.get('name') ?? '').trim();
  const rawBand = searchParams.get('band') ?? 'P4-P6';
  const bandIdx = Math.max(0, BAND_THEMES.findIndex((b) => b.band === rawBand));
  const profile: KidProfile = { name: rawName, band: BAND_THEMES[bandIdx].band, student: rawStudent };
  const bigKid = BAND_THEMES[bandIdx].band === 'P1-P3';

  const [lang, setLang] = useState<Lang>('en');
  const [items, setItems] = useState<PortfolioItem[] | null>(null);
  const [error, setError] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const seqRef = useRef(0);

  const copy = COPY[lang];

  // Fetch only in the effect body — setState happens exclusively inside the
  // async callbacks (react-hooks/set-state-in-effect). Retry below is an
  // event handler, so it may reset the error state synchronously.
  useEffect(() => {
    const student = profile.student;
    if (!student) return;
    const seq = ++seqRef.current;
    api
      .kidPortfolio(student)
      .then((data) => {
        if (seq === seqRef.current) setItems(data.items);
      })
      .catch(() => {
        if (seq === seqRef.current) setError(true);
      })
      .finally(() => {
        if (seq === seqRef.current) setRetrying(false);
      });
    return () => {
      seqRef.current += 1;
    };
  }, [profile.student]);

  const retry = () => {
    const student = profile.student;
    if (!student) return;
    const seq = ++seqRef.current;
    setError(false);
    setRetrying(true);
    api
      .kidPortfolio(student)
      .then((data) => {
        if (seq === seqRef.current) setItems(data.items);
      })
      .catch(() => {
        if (seq === seqRef.current) setError(true);
      })
      .finally(() => {
        if (seq === seqRef.current) setRetrying(false);
      });
  };

  const backQuery = (() => {
    const params = new URLSearchParams();
    if (profile.student) params.set('student', profile.student);
    if (rawName) params.set('name', rawName);
    if (profile.band) params.set('band', profile.band);
    const qs = params.toString();
    return qs ? `/chat?${qs}` : '/chat';
  })();

  const titleSize = bigKid ? 'text-2xl md:text-[26px]' : 'text-lg md:text-xl';
  const bodySize = bigKid ? 'text-base leading-relaxed' : 'text-sm leading-relaxed';
  const accent = BAND_THEMES[bandIdx].accent;

  return (
    <div className="relative flex min-h-screen flex-col bg-[#1a1a2e] font-sans text-white">
      <Starfield />

      {/* Header — logo top-left (brand kit), lang toggle + back like /chat. */}
      <header className="sticky top-0 z-10 border-b border-white/10 bg-[#1a1a2e]/85 backdrop-blur">
        <div className="mx-auto flex max-w-3xl flex-wrap items-center gap-3 px-4 py-3">
          <img src={logoWhite} alt="Dreamer AI Education" className="h-10 w-auto" />

          {profile.name && (
            <p className="text-sm font-semibold text-white/80">{copy.sub(profile.name)}</p>
          )}

          <div className="ml-auto flex items-center gap-2">
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
              to={backQuery}
              className="rounded-full border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-semibold text-white/80 hover:text-white"
            >
              {copy.back}
            </Link>
          </div>
        </div>
      </header>

      <main className="relative z-[1] mx-auto w-full max-w-3xl flex-1 px-4 py-8">
        <div className="mb-6">
          <h1 className={`font-black tracking-tight ${bigKid ? 'text-3xl' : 'text-2xl'}`}>
            {copy.gallery}
          </h1>
          {profile.name && <p className="mt-1 text-sm text-white/55">{copy.sub(profile.name)}</p>}
        </div>

        {!profile.student && (
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-12 text-center">
            <p className="text-lg font-semibold text-white/80">{copy.noStudent}</p>
            <Link
              to={backQuery}
              className="mt-5 inline-block rounded-full border border-white/20 bg-white/5 px-5 py-2 text-sm font-semibold text-white hover:border-white/50"
            >
              {copy.back}
            </Link>
          </div>
        )}

        {profile.student && error && (
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-12 text-center" role="alert">
            <p className="text-lg font-semibold text-white/80">{copy.loadError}</p>
            <button
              type="button"
              onClick={retry}
              disabled={retrying}
              className="mt-5 inline-block rounded-full border border-white/25 bg-white/10 px-5 py-2 text-sm font-bold text-white hover:bg-white/20 disabled:opacity-50"
            >
              {copy.tryAgain}
            </button>
          </div>
        )}

        {profile.student && !error && items === null && (
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-12 text-center">
            <p className="text-sm text-white/60">{copy.loading}</p>
          </div>
        )}

        {profile.student && !error && items !== null && items.length === 0 && (
          <div className="rounded-3xl border border-white/10 bg-white/5 px-6 py-14 text-center">
            <p className={`font-bold text-white ${bigKid ? 'text-xl' : 'text-lg'}`}>
              {copy.emptyTitle}
            </p>
            <p className="mx-auto mt-3 max-w-md text-sm text-white/60">{copy.emptyHint}</p>
          </div>
        )}

        {profile.student && !error && items !== null && items.length > 0 && (
          <div className={bigKid ? 'space-y-7' : 'space-y-5'}>
            {items.map((item) => (
              <article
                key={item.item_id}
                className="rounded-3xl border border-white/10 bg-white/[0.06] p-5 backdrop-blur-sm"
                style={{ borderTopColor: accent, borderTopWidth: 3 }}
              >
                <div className="flex flex-wrap items-center gap-2">
                  {item.kid_label && (
                    <span
                      className="rounded-full px-3 py-1 text-xs font-bold text-[#1a1a2e]"
                      style={{ backgroundColor: accent }}
                    >
                      {item.kid_label}
                    </span>
                  )}
                  {item.subject && <span className="text-xs text-white/40">{item.subject}</span>}
                </div>

                <h2 className={`mt-3 font-black tracking-tight text-white ${titleSize}`}>
                  {item.title}
                </h2>

                {item.description && (
                  <p className={`mt-3 text-white/85 ${bodySize}`}>{item.description}</p>
                )}

                {item.growth_note && (
                  <p className={`mt-3 border-l-2 border-white/25 pl-3 italic text-white/60 ${bigKid ? 'text-base' : 'text-sm'}`}>
                    {item.growth_note}
                  </p>
                )}

                {item.competencies_4d.length > 0 && (
                  <div className="mt-5">
                    <p className="text-[11px] font-bold uppercase tracking-wider text-white/40">
                      {copy.skillLabel}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {item.competencies_4d.map((value) => (
                        <Badge4D key={value} value={value} tone="dark" />
                      ))}
                    </div>
                  </div>
                )}

                <p className="mt-4 text-[11px] text-white/35">
                  {copy.dateLabel}: {item.achieved_at.slice(0, 10)}
                </p>
              </article>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
