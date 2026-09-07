// W4 PR-B Step 3 — parent share dialog: preview + PNG export of a
// whitelist share_card. 1:1 (square) and 9:16 (vertical) exports via
// html2canvas at scale 2 (DOM 540px -> PNG 1080px).
//
// Export technique: a fixed, off-stacking export node is mounted once; while
// a capture runs we flip it to opacity:1 for two frames (html2canvas paints
// the cloned document, so opacity:0 would render a blank PNG), capture, then
// flip back. The node sits under the dialog scrim so the user never sees it.

import { useEffect, useRef, useState } from 'react';
import html2canvas from 'html2canvas';
import type { ShareCard } from '../../lib/portfolioTypes';
import { ShareCardImage, type ShareCardVariant } from '../share/ShareCardImage';

const NAVY = '#00023D';

interface Props {
  card: ShareCard;
  onClose: () => void;
}

const VARIANTS: { id: ShareCardVariant; label: string }[] = [
  { id: 'square', label: '正方形 1:1' },
  { id: 'vertical', label: '直向 9:16' },
];

const PREVIEW_SCALE: Record<ShareCardVariant, number> = { square: 0.62, vertical: 0.48 };

export function ShareCardDialog({ card, onClose }: Props) {
  const [variant, setVariant] = useState<ShareCardVariant>('square');
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const exportRef = useRef<HTMLDivElement | null>(null);
  const exportingRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => {
      mountedRef.current = false;
      window.removeEventListener('keydown', onKey);
      // restore export node opacity on unmount regardless of capture state
      const exportNode = exportRef.current;
      if (exportNode) exportNode.style.opacity = '0';
    };
  }, [onClose]);

  const exportPng = async () => {
    const node = exportRef.current;
    if (!node || exportingRef.current) return;
    exportingRef.current = true;
    setExporting(true);
    setError(null);
    try {
      node.style.opacity = '1';
      // two frames so the browser commits the paint html2canvas clones
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      const canvas = await html2canvas(node, { scale: 2, backgroundColor: NAVY });
      if (!mountedRef.current) return;
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/png'),
      );
      if (!blob) throw new Error('canvas export failed');
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const safeName = card.display_name.replace(/\s+/g, '-');
      a.href = url;
      a.download = `${safeName}-dreamer-share-${variant}.png`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    } catch (e) {
      if (mountedRef.current) setError(e instanceof Error ? e.message : 'export failed');
    } finally {
      exportingRef.current = false;
      if (node) node.style.opacity = '0';
      if (mountedRef.current) setExporting(false);
    }
  };

  const scale = PREVIEW_SCALE[variant];
  const cardW = variant === 'square' ? 540 : 540;
  const cardH = variant === 'square' ? 540 : 960;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-label="分享卡預覽"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md overflow-hidden rounded-2xl bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-neutral-100 px-5 py-3.5">
          <h3 className="text-sm font-bold text-[#00023D]">下載分享卡</h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="關閉"
            className="rounded-full p-1 text-neutral-400 hover:bg-neutral-100 hover:text-neutral-600"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M6 6l12 12M18 6L6 18"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <div className="px-5 pt-4">
          <div className="flex gap-1 rounded-full bg-neutral-100 p-1" role="group" aria-label="卡片格式">
            {VARIANTS.map((v) => (
              <button
                key={v.id}
                type="button"
                onClick={() => setVariant(v.id)}
                aria-pressed={variant === v.id}
                className={`flex-1 rounded-full px-3 py-1.5 text-xs font-bold transition-colors ${
                  variant === v.id ? 'bg-[#00023D] text-white' : 'text-neutral-500 hover:text-neutral-700'
                }`}
              >
                {v.label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 flex max-h-[56vh] justify-center overflow-y-auto px-5 pb-2">
          <div
            style={{
              width: cardW * scale,
              height: cardH * scale,
              overflow: 'hidden',
              borderRadius: 12,
            }}
          >
            <div
              style={{
                transform: `scale(${scale})`,
                transformOrigin: 'top left',
                width: cardW,
                height: cardH,
              }}
            >
              <ShareCardImage card={card} variant={variant} />
            </div>
          </div>
        </div>

        <div className="px-5 pb-5 pt-2">
          {error && <p className="mb-2 text-xs font-semibold text-red-600">{error}</p>}
          <button
            type="button"
            onClick={exportPng}
            disabled={exporting}
            className="w-full rounded-full bg-[#00023D] px-4 py-2.5 text-sm font-bold text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {exporting ? '生成中…' : '下載 PNG'}
          </button>
          <p className="mt-2 text-center text-[11px] text-neutral-400">
            {variant === 'square' ? '1080 × 1080 px' : '1080 × 1920 px'} · 可直接分享
          </p>
        </div>
      </div>

      {/* Export node — same card, real scale, hidden below the scrim. */}
      <div
        ref={exportRef}
        aria-hidden
        style={{
          position: 'fixed',
          left: 0,
          top: 0,
          zIndex: 1,
          opacity: 0,
          pointerEvents: 'none',
        }}
      >
        <ShareCardImage card={card} variant={variant} />
      </div>
    </div>
  );
}
