// W3-B — Reusable consent indicator (media consent three-state lamp).
//
// Presentational only. Expected status values follow the backend consent
// vocabulary (see auth/consent.py: status_for_user returns
// 'unsigned' | 'agreed' | 'withdrawn' — there is no per-student media
// consent field on GET /api/parent/report yet; the dashboard wires this
// component only when a data source provides a status. Until then the
// parent dashboard simply omits it.)

export type ConsentStatus = 'unsigned' | 'agreed' | 'withdrawn';

interface ConsentIndicatorProps {
  status?: ConsentStatus | null;
  label?: string;
}

const META: Record<ConsentStatus, { dot: string; text: string }> = {
  agreed: { dot: 'bg-emerald-500', text: '已同意媒體使用' },
  unsigned: { dot: 'bg-slate-400', text: '未簽署媒體同意書' },
  withdrawn: { dot: 'bg-amber-500', text: '已撤回媒體同意' },
};

export function ConsentIndicator({ status, label = '媒體同意' }: ConsentIndicatorProps) {
  if (!status) return null;
  const meta = META[status];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-black/10 bg-white px-2 py-1 text-xs text-black/70">
      <span className={`h-2 w-2 rounded-full ${meta.dot}`} aria-hidden />
      <span>{label}：{meta.text}</span>
    </span>
  );
}
