// W3-B 步骤 3 — Class stats trio (student count / avg mastery / pending).
//
// One stat unit; the ClassLensView renders three of them side by side.
// average_mastery_pct arrives on the 0..1 backend scale — converted to a
// whole percentage for display (masteryToPercent in parentTypes).

import { masteryToPercent } from '../../lib/parentTypes';

interface ClassStatsCardProps {
  label: string;
  value: string;
  hint?: string;
  emphasize?: boolean;
}

export function ClassStatsCard({ label, value, hint, emphasize = false }: ClassStatsCardProps) {
  return (
    <div
      className={`rounded-2xl border bg-white p-4 shadow-sm ${
        emphasize ? 'border-[#00023D]/20' : 'border-black/5'
      }`}
    >
      <p className="text-xs font-medium text-black/50">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tracking-tight ${emphasize ? 'text-[#00023D]' : 'text-black/80'}`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-[11px] text-black/40">{hint}</p>}
    </div>
  );
}

/** Convenience: count card. */
export function countStat(label: string, value: number): { label: string; value: string } {
  return { label, value: String(value) };
}

/** Convenience: average mastery card (0..1 raw in → whole % out). */
export function averageMasteryStat(label: string, raw: number | null): { label: string; value: string; hint: string } {
  const pct = masteryToPercent(raw);
  return {
    label,
    value: pct === null ? '—' : `${pct}%`,
    hint: pct === null ? 'no snapshot data yet' : 'avg of latest snapshot mastery',
  };
}
