import type { BandTheme } from '../lib/mock';
import { renderBold } from './ChatMessage';
import { Dibi } from './Dibi';

interface Props {
  content: string;
  theme: BandTheme;
  // PR-D-c1-6 §L3 — explicit opt-in, same contract as AssistantMessage: only the
  // student chat surface passes `true`; default reproduces pre-L3 behaviour.
  stripSymbols?: boolean;
}

// Live-streaming answer bubble — content×N chunks render as they arrive.
// Mode / kid_label / citations / cost only appear once the result frame lands
// (the kid sees the words first; the chrome arrives with the final payload).
export function StreamingMessage({ content, theme, stripSymbols = false }: Props) {
  return (
    <article className="flex items-start gap-3" aria-live="polite">
      <div className="mt-1">
        <Dibi size={40} accent={theme.accent} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-bold text-white">{theme.mascot}</span>
        </div>
        <div
          className={`mt-2 whitespace-pre-wrap rounded-3xl rounded-tl-md border border-white/10 bg-[#252949] px-5 py-4 text-white ${theme.textScale}`}
          style={{ boxShadow: `0 0 24px ${theme.accent}22` }}
        >
          {renderBold(content, { strip: stripSymbols })}
          <span
            className="ml-0.5 inline-block h-4 w-1 animate-pulse align-middle"
            style={{ backgroundColor: theme.accent }}
            aria-hidden
          />
        </div>
      </div>
    </article>
  );
}
