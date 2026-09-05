// Stream seam — the single interface both the mock and the real WS client
// implement, so they are 1:1 swappable behind VITE_BACKEND=mock|ws.
// W2 PR#6: VITE_BACKEND defaults to 'backend' (real backend default target);
// the chat stream stays on the scripted mock for any non-'ws' value.
// Phase 7 W3-A §4.2: VITE_BACKEND=ws now resolves to the real WS client
// (GET /api/ws/chat with the auth session cookie; student via query param).
// The switch lives HERE — components never hardcode which stream they use.
import type { ChatPayload, Lang } from './mock';
import { MOCK_TURNS, LANG_CODE } from './mock';
import type { ActiveStage } from '../components/StageLoader';
import type { ChatStreamStatus, KidErrorKind } from './chatErrors';
import { createWsChatStream } from './chatWs';

export type StreamHandlers = {
  onStages: (stages: ActiveStage[]) => void; // ← stage_start / stage_end
  onProgress: (pct: number) => void; // ← progress 0–100 (wired in Step 1, UI expansion later)
  onProgressNote?: (note: string | null) => void; // ← progress kid note (real WS)
  onContent: (chunk: string) => void; // ← content×N (true streaming render in W3-A)
  onResult: (payload: ChatPayload) => void; // ← result + done
  onStatus?: (status: ChatStreamStatus) => void; // ← ws lifecycle (connecting/streaming/disconnected/reconnecting/failed)
  onError?: (kind: KidErrorKind) => void; // ← kid-safe error class (raw error never surfaces)
};

export interface StreamContext {
  student?: string; // 8-char mask prefix passed to the WS handshake
}

export type PlayStream = (
  input: string,
  band: ChatPayload['age_band'],
  lang: Lang,
  h: StreamHandlers,
  ctx?: StreamContext,
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
  // Emit content in chunks (streaming render is wired for the real WS path;
  // the mock result arrives whole shortly after — chunks stay harmless).
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

// Env switch — THE single mock→real switch point for the chat stream.
//   VITE_BACKEND=ws     → real WS client (/api/ws/chat + handshake gate)
//   anything else       → scripted mock (VITE_BACKEND=mock|backend, historical
//                          default keeps the demo alive pre-deploy)
export function createStream(): PlayStream {
  const backend = import.meta.env.VITE_BACKEND ?? 'backend';
  if (backend === 'ws') {
    console.info('[stream] VITE_BACKEND=ws → real WS chat client');
    return (input, band, lang, h, ctx) => {
      // Fill optional lifecycle callbacks so the WS client sees a full handler
      // set (mock callers keep working untouched).
      const handlers = {
        onStages: h.onStages,
        onProgress: h.onProgress,
        onProgressNote: h.onProgressNote ?? (() => {}),
        onContent: h.onContent,
        onResult: h.onResult,
        onStatus: h.onStatus ?? (() => {}),
        onError: h.onError ?? (() => {}),
      };
      return createWsChatStream(input, band, lang, handlers, ctx ?? { student: undefined });
    };
  }
  console.info(`[stream] VITE_BACKEND=${backend} → scripted mock stream (set =ws for the real backend)`);
  return playStream;
}

export function isRealWsMode(): boolean {
  return (import.meta.env.VITE_BACKEND ?? 'backend') === 'ws';
}
