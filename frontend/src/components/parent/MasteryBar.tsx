// W3-B — Reusable mastery progress bar.
//
// Backend mastery_pct is stored 0..1 (rolling average). Pass the raw value;
// the bar multiplies by 100 internally. Brand color #00023D.

interface MasteryBarProps {
  /** Raw mastery 0..1 (backend scale). */
  mastery: number | null | undefined;
  /** Optional label shown at the right of the bar (e.g. "已達標"). */
  label?: string;
  /** Accessible name for the bar. */
  title?: string;
  className?: string;
}

export function MasteryBar({ mastery, label, title, className = '' }: MasteryBarProps) {
  const pct =
    mastery === null || mastery === undefined
      ? null
      : Math.min(100, Math.max(0, Math.round(mastery * 100)));

  return (
    <div className={`w-full ${className}`}>
      <div className="flex items-center justify-between gap-3 text-xs">
        {title ? <span className="text-black/60">{title}</span> : <span />}
        {label !== undefined && (
          <span className="shrink-0 font-medium text-black/80">{label}</span>
        )}
      </div>
      <div
        role="progressbar"
        aria-valuenow={pct ?? 0}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={title ?? 'mastery'}
        className="mt-1.5 h-2 w-full overflow-hidden rounded-full bg-black/10"
      >
        {pct !== null && (
          <div
            className="h-full rounded-full bg-[#00023D] transition-all"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}
