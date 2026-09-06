// W3-B — Reusable duration display.
//
// Backend summary.total_duration_seconds is number|null:
//   null = legacy rows without a recorded duration = "no data".
// Instruction 4.x: when null show 「暫無數據」— never a fake 0.

interface DurationDisplayProps {
  seconds: number | null | undefined;
  label?: string;
}

export function DurationDisplay({ seconds, label = '學習時長' }: DurationDisplayProps) {
  if (seconds === null || seconds === undefined) {
    return (
      <span className="text-xs text-black/40">
        {label}：<span className="text-black/60">暫無數據</span>
      </span>
    );
  }
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const text = mins > 0 ? `${mins} 分 ${secs} 秒` : `${secs} 秒`;
  return (
    <span className="text-xs text-black/60">
      {label}：<span className="font-medium text-black/80">{text}</span>
    </span>
  );
}
