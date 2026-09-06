// W3-B — Reusable mastery delta badge.
//
// Backend report.topics[].mastery_delta is a 0..1 float (may be negative)
// meaning the change between period start and end. The badge renders it as
// whole percentage points, independently from the progress bar (instruction
// 4.1: delta is NOT baked into the bar). Copy is intentionally minimal and
// locale-agnostic (+/- N 百分點); backend narrative text is rendered by the
// digest components, not re-invented here.

interface DeltaBadgeProps {
  /** Raw delta 0..1, negative allowed; null/undefined renders nothing. */
  delta: number | null | undefined;
}

export function DeltaBadge({ delta }: DeltaBadgeProps) {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return null;
  const points = Math.round(delta * 100);
  if (points === 0) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-black/5 px-2 py-0.5 text-xs text-black/50">
        持平
      </span>
    );
  }
  const up = points > 0;
  const text = `${up ? '+' : ''}${points} 百分點`;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs ${
        up ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
      }`}
    >
      <span aria-hidden>{up ? '▲' : '▼'}</span>
      <span>{text}</span>
    </span>
  );
}
