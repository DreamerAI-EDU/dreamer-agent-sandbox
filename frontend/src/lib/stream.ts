// Stream seam — the single interface both the mock and the future WS client
// implement, so they are 1:1 swappable behind VITE_BACKEND=mock|ws.
// W2 PR#6: VITE_BACKEND now defaults to 'backend' (the real backend is the
// default deployment target). The chat seam is NOT wired to a WS stream yet —
// any non-'ws' value keeps the scripted MOCK_TURNS demo alive for W3 to
// replace. The five real REST pages bypass this seam entirely (lib/api.ts).
import type { ChatPayload, Lang } from './mock';
import { MOCK_TURNS, LANG_CODE } from './mock';
import type { ActiveStage } from '../components/StageLoader';

export type StreamHandlers = {
  onStages: (stages: ActiveStage[]) => void; // ← stage_start / stage_end
  onProgress: (pct: number) => void; // ← progress 0–100 (wired in Step 1, UI expansion later)
  onContent: (chunk: string) => void; // ← content×N (reserved, not rendered in Step 1 MVP)
  onResult: (payload: ChatPayload) => void; // ← result + done
};

export type PlayStream = (
  input: string,
  band: ChatPayload['age_band'],
  lang: Lang,
  h: StreamHandlers,
) => () => void;

// Resolve which mock scripted turn matches the user's input; fall back to
// cycling by hash so any input still produces a demo answer.
function pickTurn(input: string, lang: Lang): number {
  const idx = MOCK_TURNS.findIndex((t) => t.user[lang] === input.trim());
  if (idx !== -1) return idx;
  let hash = 0;
  for (let i = 0; i < input.length; i++) hash = (hash * 31 + input.charCodeAt(i)) >>> 0;
  return hash % MOCK_TURNS.length;
}

// Simulates the WS event stream: stage_start → progress → content×N → stage_end → result → done.
// Real timings run 56–100s; demo plays each stage in ~1.4s.
export function playStream(
  input: string,
  band: ChatPayload['age_band'],
  lang: Lang,
  h: StreamHandlers,
): () => void {
  const script = MOCK_TURNS[pickTurn(input, lang)];
  const timers: ReturnType<typeof setTimeout>[] = [];
  const live: ActiveStage[] = [];

  script.stages.forEach((s, i) => {
    timers.push(
      setTimeout(() => {
        live.push({ stage: s.stage, done: false });
        h.onStages([...live]);
        h.onProgress(Math.round((i / script.stages.length) * 100));
      }, i * 1400),
    );
    timers.push(
      setTimeout(() => {
        live[i] = { ...live[i], done: true };
        h.onStages([...live]);
      }, i * 1400 + 1100),
    );
  });

  const content = script.payload[band][lang];
  // Emit content in chunks (reserved for Step 1.5 streaming render; MVP just collects).
  const chunkSize = 40;
  for (let i = 0; i < content.length; i += chunkSize) {
    const chunk = content.slice(i, i + chunkSize);
    timers.push(setTimeout(() => h.onContent(chunk), script.stages.length * 1400 + 100 + i));
  }

  timers.push(
    setTimeout(
      () => {
        h.onProgress(100);
        h.onResult({
          content,
          mode: script.mode,
          lang_code: LANG_CODE[lang],
          age_band: band,
          kid_label: script.kid_label,
          citations: script.citations,
          cost_summary: { tokens_in: 412, tokens_out: 268, est_cost_hkd: 0.041 },
        });
      },
      script.stages.length * 1400 + 400,
    ),
  );

  return () => timers.forEach(clearTimeout);
}

// Env switch: VITE_BACKEND=backend (default) → real backend is the default
// deployment target; the chat stream remains on the mock until W3 wires 'ws'.
export function createStream(): PlayStream {
  const backend = import.meta.env.VITE_BACKEND ?? 'backend';
  if (backend === 'ws') {
    console.warn('[stream] VITE_BACKEND=ws not wired until Step 2 deployment; falling back to mock.');
  }
  return playStream;
}
