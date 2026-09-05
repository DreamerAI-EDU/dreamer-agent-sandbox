import type { ChatPayload, CostSummaryHkd, CostSummaryUsd, BandTheme, Lang } from '../lib/mock';
import { MODE_BADGE } from '../lib/mock';
import { Dibi } from './Dibi';

interface Props {
  payload: ChatPayload;
  theme: BandTheme;
  lang: Lang;
}

// Minimal **bold** renderer — kid replies only ever use bold, never raw HTML.
export function renderBold(text: string) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith('**') && part.endsWith('**') ? (
      <strong key={i}>{part.slice(2, -2)}</strong>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

// cost_summary can arrive in the Hermes HKD shape or the real DeepTutor USD
// shape (nested result.metadata.metadata.cost_summary, flat fallback). Render
// the actual currency label — never invent an exchange rate.
function formatCost(cost: ChatPayload['cost_summary']): string | null {
  const hasAny = (c: CostSummaryHkd) => c.tokens_in + c.tokens_out > 0;
  const hasAnyUsd = (c: CostSummaryUsd) => c.total_tokens > 0 || c.total_calls > 0;
  if ('est_cost_hkd' in cost && cost.est_cost_hkd !== undefined && hasAny(cost)) {
    const c = cost as CostSummaryHkd;
    return `${c.tokens_in + c.tokens_out} tokens · ≈ HK$${c.est_cost_hkd.toFixed(3)}`;
  }
  if ('total_cost_usd' in cost && hasAnyUsd(cost)) {
    const c = cost as CostSummaryUsd;
    return `${c.total_tokens} tokens · ≈ $${c.total_cost_usd.toFixed(4)} USD`;
  }
  return null; // no-data marker → render layer shows "—"
}

export function AssistantMessage({ payload, theme, lang }: Props) {
  const badge = MODE_BADGE[payload.mode];
  const citationsLabel = lang === 'en' ? 'From the Dreamer library' : lang === 'hk' ? '出自 Dreamer 知識庫' : '出自 Dreamer 知识库';
  const costLine = formatCost(payload.cost_summary);

  return (
    <article className="flex items-start gap-3">
      <div className="mt-1">
        <Dibi size={40} accent={theme.accent} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-bold text-white">{theme.mascot}</span>
          <span
            className="flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-bold text-white"
            style={{ borderColor: badge.color }}
          >
            <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: badge.color }} aria-hidden />
            {badge[lang]}
          </span>
          {payload.kid_label && (
            <span className="rounded-full border border-dashed border-white/35 px-2.5 py-0.5 text-xs font-semibold text-white/70">
              {payload.kid_label}
            </span>
          )}
        </div>

        <div
          className={`mt-2 rounded-3xl rounded-tl-md border border-white/10 bg-[#252949] px-5 py-4 text-white ${theme.textScale}`}
          style={{ boxShadow: `0 0 24px ${theme.accent}22` }}
        >
          {renderBold(payload.content)}
        </div>

        {payload.citations.length > 0 && (
          <div className="mt-2 text-xs text-white/60">
            <span className="font-bold uppercase tracking-wide text-white/45">{citationsLabel}</span>
            <ul className="mt-1 space-y-0.5">
              {payload.citations.map((c) => (
                <li key={`${c.topic_id}-${c.kb}-${c.title}`} className="flex items-baseline gap-1.5">
                  <span aria-hidden>·</span>
                  <span className="font-semibold text-white/80">{c.title}</span>
                  {(c.kb || c.topic_id) && (
                    <span className="text-white/35">
                      ({c.kb}
                      {c.kb && c.topic_id ? ' / ' : ''}
                      {c.topic_id})
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* cost_summary: surfaced for tutor/parent oversight, muted for kids.
            no-data branch: only show when cost data exists, else "—". */}
        <p className="mt-2 text-[11px] tabular-nums text-white/30">{costLine ?? '—'}</p>
      </div>
    </article>
  );
}
