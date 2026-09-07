// W4 PR-B — parent portfolio view (/parent · view=portfolio).
//
// Parent-facing surface (R2): shows every shared portfolio item plus one
// share_card payload per item; the share affordance lives ONLY here, never
// on the kid-facing /portfolio page.
//
// Race guard: requests are sequenced with an increasing id so a stale
// response for a previously-selected child can never overwrite the current
// child's portfolio (W3-B deep-link rule).
//
// Empty state is parent-facing copy ("仲未有作品展出" direction) — distinct
// from the kid-facing welcome empty state on /portfolio.

import { useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import type { ParentPortfolioResponse, ShareCard } from '../../lib/portfolioTypes';
import { Badge4D } from '../portfolio/Badge4D';
import { ShareCardDialog } from './ShareCardDialog';

interface Props {
  studentId: string;
}

export function PortfolioView({ studentId }: Props) {
  const [envelope, setEnvelope] = useState<ParentPortfolioResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [shareCard, setShareCard] = useState<ShareCard | null>(null);
  const seqRef = useRef(0);

  useEffect(() => {
    const seq = ++seqRef.current;
    setLoading(true);
    setError('');
    setEnvelope(null);
    api
      .parentPortfolio(studentId)
      .then((data) => {
        // stale guard: only the latest request may commit state
        if (seq !== seqRef.current) return;
        setEnvelope(data);
      })
      .catch((err: unknown) => {
        if (seq !== seqRef.current) return;
        setError(err instanceof ApiError ? err.message : '載入作品失敗');
      })
      .finally(() => {
        if (seq === seqRef.current) setLoading(false);
      });
    return () => {
      // mark in-flight request as stale when the child changes / unmounts
      seqRef.current += 1;
    };
  }, [studentId]);

  if (loading && !envelope) {
    return (
      <div className="rounded-2xl border border-black/5 bg-white px-5 py-10 text-center text-sm text-black/50">
        載入中…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-8 text-center text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (!envelope) return null;

  // Parent-facing empty state (kid page has its own welcome copy).
  if (envelope.empty || envelope.items.length === 0) {
    return (
      <div className="rounded-2xl border border-black/5 bg-white px-5 py-12 text-center">
        <p className="text-base font-semibold text-[#00023D]">
          {envelope.student.display_name} 仲未有作品展出
        </p>
        <p className="mt-2 text-sm text-black/45">
          當小朋友完成挑戰同專題，作品會自動喺呢度出現。
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {envelope.items.map((item, i) => {
        const card = envelope.share_cards[i];
        return (
          <article
            key={item.item_id}
            className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm"
          >
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-bold text-[#00023D]">{item.title}</h3>
                  {item.kid_label && (
                    <span className="rounded-full bg-[#00023D]/8 px-2.5 py-0.5 text-xs font-semibold text-[#00023D]">
                      {item.kid_label}
                    </span>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-black/35">
                  {item.achieved_at.slice(0, 10)} · {item.subject}
                </p>
              </div>
              {card && (
                <button
                  type="button"
                  onClick={() => setShareCard(card)}
                  className="shrink-0 rounded-full border border-[#00023D]/30 bg-white px-4 py-1.5 text-xs font-bold text-[#00023D] transition-colors hover:bg-[#00023D] hover:text-white"
                >
                  分享
                </button>
              )}
            </div>

            {item.description && (
              <p className="mt-3 text-sm leading-relaxed text-black/70">{item.description}</p>
            )}

            {item.growth_note && (
              <p className="mt-3 border-l-2 border-[#00023D]/20 pl-3 text-sm italic text-black/55">
                {item.growth_note}
              </p>
            )}

            {item.competencies_4d.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {item.competencies_4d.map((value) => (
                  <Badge4D key={value} value={value} />
                ))}
              </div>
            )}
          </article>
        );
      })}

      {shareCard && <ShareCardDialog card={shareCard} onClose={() => setShareCard(null)} />}
    </div>
  );
}
