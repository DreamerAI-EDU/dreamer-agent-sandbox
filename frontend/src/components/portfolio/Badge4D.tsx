// W4 PR-B — 4D badge shared renderer.
// Backend vocabulary (dream/discover/design/deliver) is rendered verbatim —
// capitalization only (R5: no client-side label translation).

export function Badge4D({ value, tone = 'light' }: { value: string; tone?: 'light' | 'dark' }) {
  if (tone === 'dark') {
    return (
      <span className="inline-flex items-center rounded-full border border-white/35 px-3 py-1 text-xs font-bold capitalize tracking-wide text-white">
        {value}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full border border-[#00023D]/25 bg-white px-3 py-1 text-xs font-bold capitalize tracking-wide text-[#00023D]">
      {value}
    </span>
  );
}
