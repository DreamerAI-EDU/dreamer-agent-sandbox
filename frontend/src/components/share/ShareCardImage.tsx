// W4 PR-B Step 3 — share_card image renderer (client-side DOM -> canvas).
//
// Consumes ONLY the whitelist share_card payload (R3): display_name /
// item_id / title / artifact_summary / competencies_4d / kid_label / brand /
// generated_at. No extra data field is ever drawn (the logo and the brand
// name are the payload's own `brand` row, not invented copy).
//
// Export sizing: the DOM is laid out at fixed px (square 540x540, vertical
// 540x960) and exported at canvas scale 2 → 1080px PNGs (1:1 and 9:16).
// html2canvas cannot capture CSS features it does not support; keep the card
// to flat solid colors + plain fonts only (no oklch, no backdrop-filter).

import type { ShareCard } from '../../lib/portfolioTypes';
import logoWhite from '../../assets/dreamer-logo-white.png';

export type ShareCardVariant = 'square' | 'vertical';

const NAVY = '#00023D'; // brand kit primary (R7)
const WHITE = '#ffffff';

const LAYOUT: Record<ShareCardVariant, { width: number; height: number; pad: number }> = {
  square: { width: 540, height: 540, pad: 44 },
  vertical: { width: 540, height: 960, pad: 48 },
};

/** Badge values are backend vocabulary — capitalize only, never translate. */
function BadgePill({ value }: { value: string }) {
  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        border: `1.5px solid rgba(255,255,255,0.45)`,
        borderRadius: 999,
        padding: '8px 18px',
      }}
    >
      <span
        style={{
          color: WHITE,
          fontSize: 17,
          fontWeight: 800,
          letterSpacing: '0.08em',
          textTransform: 'capitalize',
        }}
      >
        {value}
      </span>
    </div>
  );
}

export function ShareCardImage({ card, variant }: { card: ShareCard; variant: ShareCardVariant }) {
  const { width, height, pad } = LAYOUT[variant];
  const vertical = variant === 'vertical';

  return (
    <div
      data-share-card={variant}
      style={{
        position: 'relative',
        width,
        height,
        backgroundColor: NAVY,
        color: WHITE,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang HK", "Microsoft JhengHei", sans-serif',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        padding: pad,
        boxSizing: 'border-box',
      }}
    >
      {/* Top brand row — brand name from the payload (`brand`), logo asset. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <img src={logoWhite} alt="" style={{ height: 40, width: 'auto', display: 'block' }} />
        <span style={{ fontSize: 21, fontWeight: 800, letterSpacing: '0.02em' }}>{card.brand}</span>
      </div>

      {/* Kid name + label — first name only (R6 / B24). */}
      <div style={{ marginTop: vertical ? 64 : 40 }}>
        <div style={{ fontSize: vertical ? 60 : 50, fontWeight: 900, lineHeight: 1.1 }}>
          {card.display_name}
        </div>
        <div
          style={{
            marginTop: 12,
            display: 'inline-block',
            borderRadius: 999,
            backgroundColor: 'rgba(255,255,255,0.12)',
            padding: '8px 18px',
            fontSize: 21,
            fontWeight: 700,
          }}
        >
          {card.kid_label}
        </div>
      </div>

      {/* Artifact — title + summary. */}
      <div style={{ marginTop: vertical ? 44 : 30, flex: 1, minHeight: 0 }}>
        <div style={{ fontSize: vertical ? 34 : 27, fontWeight: 800, lineHeight: 1.25 }}>
          {card.title}
        </div>
        <div
          style={{
            marginTop: 14,
            fontSize: vertical ? 21 : 17,
            lineHeight: 1.7,
            color: 'rgba(255,255,255,0.85)',
            maxHeight: vertical ? 290 : 132,
            overflow: 'hidden',
          }}
        >
          {card.artifact_summary}
        </div>
      </div>

      {/* 4D badges — verbatim array (R5). */}
      {card.competencies_4d.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 18 }}>
          {card.competencies_4d.map((value) => (
            <BadgePill key={value} value={value} />
          ))}
        </div>
      )}

      {/* Footer — generated date only (no invented fields). */}
      <div
        style={{
          marginTop: 24,
          paddingTop: 18,
          borderTop: '1px solid rgba(255,255,255,0.18)',
          fontSize: 15,
          color: 'rgba(255,255,255,0.55)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span>{card.generated_at.slice(0, 10)}</span>
        <span style={{ fontWeight: 700 }}>{card.brand}</span>
      </div>
    </div>
  );
}
