// Real WS chat client — Phase 7 W3-A §4.2.
//
// Implements the Kid-Safe streaming path for VITE_BACKEND=ws:
//   GET /api/ws/chat?student=<mask>   (same-origin; auth_session cookie rides
//                                      along automatically — never in JS state)
//   handshake gate on the server (401/403 rejected at HTTP layer) → 101 →
//   client sends the capability frame → upstream relays the unified WS event
//   stream: session → stage_start → progress → content×N → stage_end →
//   result → done (done = terminal).
//
// Design rules honoured here:
//   - one chat session ⇒ one WS connection; one WS ⇒ exactly one reader
//     (the single onmessage handler below)
//   - reconnect: exponential backoff + resume via subscribe_session(after_seq)
//     so a still-running turn replays the tail it missed
//   - a result-less done, or a resume that yields no events, degrades into a
//     kid-safe turn-lost error — never a hanging spinner
//   - cost_summary is read from the nested result.metadata.metadata.cost_summary
//     with flat fallback result.metadata.cost_summary
//   - raw server strings only go to the console — children see chatErrors copy

import type { ChatPayload, CostSummaryUsd, Lang } from './mock';
import { MOCK_NO_DATA_COST } from './mock';
import type { ActiveStage } from '../components/StageLoader';
import type { ChatStreamStatus, KidErrorKind } from './chatErrors';

// Frame keys observed on the real unified WS (docs/phase2-websocket.md +
// real-container probe 2026-09-05). type is always present; everything else is
// guarded before use so an unknown server revision never crashes the kid UI.
interface RawFrame {
  type?: unknown;
  stage?: unknown;
  content?: unknown;
  seq?: unknown;
  session_id?: unknown;
  turn_id?: unknown;
  error_code?: unknown;
  metadata?: Record<string, unknown>;
}

interface ChatSource {
  kb: string;
  topic_id: string;
  title: string;
}

const WS_PATH = '/api/ws/chat';
const MAX_RETRIES = 5; // 1s → 2s → 4s → 8s → 16s (+ jitter)
const RESUME_SILENCE_MS = 8000; // reconnect got no replay events → turn lost
const JITTER_MS = 300;

export interface WsStreamContext {
  student?: string; // 8-char mask prefix, from ?student= (full ids never enter state)
}

function delayMs(attempt: number): number {
  const base = Math.min(1000 * 2 ** (attempt - 1), 16000);
  return base + Math.floor(Math.random() * JITTER_MS);
}

function getStr(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

function getNum(v: unknown): number {
  return typeof v === 'number' ? v : 0;
}

function pick<T extends Record<string, unknown>, K extends keyof T>(obj: T, ...keys: K[]): T[K] | undefined {
  for (const k of keys) {
    const v = obj[k];
    if (v !== undefined && v !== null) return v as T[K];
  }
  return undefined;
}

// Upstream cost_summary is {total_cost_usd, total_tokens, ...}; the response
// contract keeps the same seven top-level fields, so we surface the USD shape
// verbatim and let the render layer show the right currency label.
function readCostSummary(resultMeta: Record<string, unknown> | undefined): ChatPayload['cost_summary'] {
  const nestedMeta = pick(resultMeta ?? {}, 'metadata');
  const cost =
    (nestedMeta && typeof nestedMeta === 'object'
      ? pick(nestedMeta as Record<string, unknown>, 'cost_summary')
      : undefined) ??
    (resultMeta ? pick(resultMeta, 'cost_summary') : undefined);

  if (cost && typeof cost === 'object') {
    const c = cost as Record<string, unknown>;
    if (typeof c.total_cost_usd === 'number') {
      return {
        total_tokens: getNum(c.total_tokens),
        total_calls: getNum(c.total_calls),
        prompt_tokens: getNum(c.prompt_tokens),
        completion_tokens: getNum(c.completion_tokens),
        total_cost_usd: c.total_cost_usd,
      } satisfies CostSummaryUsd;
    }
    // Flat fallback not available → no-data marker (render shows "—").
  }
  return MOCK_NO_DATA_COST;
}

function normalizeSource(item: unknown): ChatSource | null {
  if (!item || typeof item !== 'object') return null;
  const o = item as Record<string, unknown>;
  const title = getStr(pick(o, 'title'));
  const kb = getStr(pick(o, 'kb', 'source', 'source_id', 'library'));
  const topicId = getStr(pick(o, 'topic_id', 'doc_id', 'chunk_id'));
  if (!title && !kb && !topicId) return null;
  return { kb, topic_id: topicId, title };
}

function mergeSources(list: unknown[], into: ChatSource[]): void {
  for (const item of list) {
    const s = normalizeSource(item);
    if (s && !into.some((x) => x.title === s.title && x.kb === s.kb && x.topic_id === s.topic_id)) {
      into.push(s);
    }
  }
}

// ---- cancellation token shared across every async path ----
interface Cancellable {
  cancelled: boolean;
}

function clearAll(c: Cancellable): void {
  c.cancelled = true;
}

export function createWsChatStream(
  input: string,
  band: ChatPayload['age_band'],
  lang: Lang,
  h: {
    onStages: (stages: ActiveStage[]) => void;
    onProgress: (pct: number) => void;
    onProgressNote: (note: string | null) => void;
    onContent: (chunk: string) => void;
    onResult: (payload: ChatPayload) => void;
    onStatus: (s: ChatStreamStatus) => void;
    onError: (kind: KidErrorKind) => void;
  },
  ctx: WsStreamContext,
): () => void {
  const student = (ctx.student ?? '').trim();
  if (!student) {
    // No profile in the URL — never even try to open a socket.
    console.warn('[chat-ws] no student mask in query params; refusing to open WS');
    queueMicrotask(() => h.onError('no-student'));
    return () => {};
  }

  const langCode = lang === 'en' ? 'en' : lang === 'hk' ? 'zh-hk' : 'zh-cn';
  const url = `${window.location.origin}${WS_PATH}?student=${encodeURIComponent(student)}`;

  const c: Cancellable = { cancelled: false };

  let ws: WebSocket | null = null;
  let attempt = 0;
  let closedByUser = false;
  let handshakeEvaluated = false; // only run the 401/403 diagnostic once
  let resultSeen = false;
  let doneSeen = false;

  // Turn state (one session ⇒ one connection ⇒ one turn at a time)
  let sessionId = '';
  let lastSeq = 0;
  const chunks: string[] = [];
  const sources: ChatSource[] = [];
  const live: ActiveStage[] = [];

  // Reconnect resume markers
  let resumeHangTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const clearTimers = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (resumeHangTimer) clearTimeout(resumeHangTimer);
    reconnectTimer = null;
    resumeHangTimer = null;
  };

  const fail = (kind: KidErrorKind) => {
    if (c.cancelled) return;
    // Turn is over from the client's perspective — no further automatic
    // retries; the user retries manually which opens a fresh stream.
    closedByUser = true;
    clearTimers();
    h.onStatus('failed');
    h.onError(kind);
    safeClose();
  };

  const safeClose = () => {
    try {
      ws?.close();
    } catch {
      /* already closed */
    }
  };

  const finishQuietly = () => {
    // Result already delivered to the UI — a missing done/terminal frame is
    // harmless; close without surfacing an error.
    if (c.cancelled) return;
    closedByUser = true;
    clearTimers();
    h.onStatus('idle');
    safeClose();
  };

  const startResumeHangWatch = () => {
    if (resumeHangTimer) clearTimeout(resumeHangTimer);
    resumeHangTimer = setTimeout(() => {
      if (c.cancelled) return;
      if (resultSeen) {
        console.info('[chat-ws] resume silent after result — treating as terminal');
        finishQuietly();
        return;
      }
      // Server did not replay anything for the old turn → turn is gone
      // (server restarted / bus unregistered). Degrade cleanly.
      console.warn('[chat-ws] resume silent for 8s — turn no longer replayable');
      fail('turn-lost');
    }, RESUME_SILENCE_MS);
  };

  const clearResumeHangWatch = () => {
    if (resumeHangTimer) clearTimeout(resumeHangTimer);
    resumeHangTimer = null;
  };

  const sendFrame = (payload: Record<string, unknown>) => {
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    } else {
      console.warn('[chat-ws] send attempted while socket not open', payload.type);
    }
  };

  const startTurn = () => {
    // Capability frame — contract keys ONLY (learning #14: an unknown config
    // key silently drops DeepTutor into stub mode). language rides as the
    // top-level field per docs/phase2-websocket.md.
    sendFrame({
      type: 'message',
      capability: 'chat',
      content: input,
      language: langCode,
      session_id: sessionId, // '' on first start; server assigns unified_xxx
    });
  };

  const resumeTurn = () => {
    // Reconnect: ask the server to replay the tail of the still-running turn.
    sendFrame({
      type: 'subscribe_session',
      session_id: sessionId,
      after_seq: lastSeq,
    });
    startResumeHangWatch();
  };

  const buildPayload = (): ChatPayload => {
    const meta = lastResultMeta ?? {};
    const content = chunks.join('').trim() || getStr(meta.response);
    if (!('kid_label' in meta)) {
      // Upstream chat events carry no kid persona label — mock-only field,
      // surfaced empty (render hides the badge) instead of inventing copy.
      console.info('[chat-ws] upstream has no kid_label; ChatMessage hides badge');
    }
    if (!('mode' in meta)) {
      console.info('[chat-ws] upstream has no mode field; falling back to DIRECT');
    }
    return {
      content,
      mode: 'DIRECT', // upstream chat stream has no mode concept — mock-only
      lang_code: langCode,
      age_band: band,
      kid_label: '', // no upstream persona label (see console note above)
      citations: sources,
      cost_summary: readCostSummary(meta),
    };
  };

  let lastResultMeta: Record<string, unknown> | undefined;

  const emitResult = () => {
    if (resultSeen) return;
    resultSeen = true;
    const payload = buildPayload();
    if (!payload.content) {
      console.warn('[chat-ws] result with empty content — turn-lost path');
      fail('turn-lost');
      return;
    }
    h.onResult(payload);
  };

  const handleFrame = (raw: unknown) => {
    if (!raw || typeof raw !== 'object') {
      console.warn('[chat-ws] non-object frame dropped');
      return;
    }
    const ev = raw as RawFrame;
    const type = getStr(ev.type);
    const seq = getNum(ev.seq);
    if (seq > lastSeq) lastSeq = seq;
    const meta = ev.metadata && typeof ev.metadata === 'object' ? ev.metadata : undefined;

    switch (type) {
      case 'session': {
        sessionId = getStr(ev.session_id) || getStr(pick(meta ?? {}, 'session_id'));
        h.onProgress(0);
        h.onStatus('streaming');
        break;
      }
      case 'stage_start': {
        const stage = getStr(ev.stage);
        live.push({ stage, done: false });
        h.onStages([...live]);
        break;
      }
      case 'progress': {
        // Unified progress events carry {current, total} both 0 for chat and a
        // kid-friendly label in content/metadata.label. Surface the note text.
        const note = getStr(ev.content) || getStr(pick(meta ?? {}, 'label')) || getStr(pick(meta ?? {}, 'text'));
        h.onProgressNote(note || null);
        h.onProgress(Math.round(getNum(pick(meta ?? {}, 'current'))));
        break;
      }
      case 'content': {
        const chunk = getStr(ev.content);
        if (chunk) {
          chunks.push(chunk);
          h.onContent(chunk);
        }
        break;
      }
      case 'sources': {
        const list = Array.isArray(ev.content) ? ev.content : Array.isArray(pick(meta ?? {}, 'sources')) ? (pick(meta ?? {}, 'sources') as unknown[]) : [];
        mergeSources(list, sources);
        break;
      }
      case 'stage_end': {
        if (live.length > 0) live[live.length - 1] = { ...live[live.length - 1], done: true };
        h.onStages([...live]);
        break;
      }
      case 'result': {
        lastResultMeta = meta;
        emitResult();
        break;
      }
      case 'done': {
        doneSeen = true;
        clearResumeHangWatch();
        if (!resultSeen) {
          // Result was never emitted (rare) — build the contract payload from
          // what content events delivered; empty → kid-safe turn-lost.
          emitResult();
        }
        h.onStatus('streaming'); // ensure final UI flush before idle
        if (!c.cancelled) {
          h.onStatus('idle');
        }
        safeClose();
        break;
      }
      case 'error': {
        const code = getStr(ev.error_code);
        const msg = getStr(ev.content) || getStr(pick(meta ?? {}, 'error'));
        console.error('[chat-ws] server error frame', code, msg);
        clearResumeHangWatch();
        fail(code === 'upstream_unavailable' || code === '' ? 'upstream' : 'upstream');
        break;
      }
      default: {
        // session_meta and any future server extension are non-contract —
        // log only, never surface to the kid.
        console.debug('[chat-ws] non-contract frame ignored', type);
        break;
      }
    }
  };

  const connect = () => {
    if (c.cancelled || closedByUser) return;
    attempt += 1;
    h.onStatus(attempt === 1 ? 'connecting' : 'reconnecting');
    try {
      ws = new WebSocket(url);
    } catch (err) {
      console.error('[chat-ws] constructor failed', err);
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      if (c.cancelled) return;
      if (!sessionId) startTurn();
      else resumeTurn();
    };

    ws.onmessage = (msg) => {
      if (c.cancelled) return;
      let data: unknown;
      try {
        data = JSON.parse(String(msg.data));
      } catch {
        console.warn('[chat-ws] non-JSON message dropped');
        return;
      }
      handleFrame(data);
    };

    ws.onerror = () => {
      // onclose follows; do the work there so we only have one close path.
      console.error('[chat-ws] socket error (attempt', attempt, ')');
    };

    ws.onclose = () => {
      if (c.cancelled || closedByUser) return;
      if (doneSeen) return; // terminal frame already handled
      clearResumeHangWatch();
      h.onStatus('disconnected');

      if (!handshakeEvaluated && attempt === 1) {
        handshakeEvaluated = true;
        void evaluateHandshakeRejection().then((kind) => {
          if (c.cancelled) return;
          if (kind === 'auth' || kind === 'permission') {
            console.error('[chat-ws] handshake rejected at HTTP layer — no retry', kind);
            fail(kind);
            return;
          }
          scheduleReconnect();
        });
      } else {
        scheduleReconnect();
      }
    };
  };

  // The browser WebSocket API hides HTTP status on upgrade failure. Run one
  // same-origin /api/auth/me probe to tell "session bad (401/403)" apart from
  // "session fine but this socket was refused (ownership/confirmation)".
  const evaluateHandshakeRejection = async (): Promise<'auth' | 'permission' | 'network'> => {
    try {
      const resp = await fetch('/api/auth/me', { credentials: 'include', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
      if (resp.status === 401 || resp.status === 403) return 'auth';
      return 'permission'; // session alive but WS gate refused → ownership/class gate
    } catch {
      return 'network';
    }
  };

  const scheduleReconnect = () => {
    if (c.cancelled || closedByUser || doneSeen) return;
    if (resultSeen) {
      // Full answer already reached the UI; a terminal done frame was the only
      // thing missing — no point retrying the socket.
      console.info('[chat-ws] drop after result — finishing quietly');
      finishQuietly();
      return;
    }
    if (attempt >= MAX_RETRIES) {
      console.error('[chat-ws] max retries reached', attempt);
      fail('network');
      return;
    }
    const wait = delayMs(attempt);
    h.onStatus('reconnecting');
    console.info(`[chat-ws] reconnect in ${wait}ms (attempt ${attempt}/${MAX_RETRIES})`);
    reconnectTimer = setTimeout(() => {
      if (!c.cancelled) connect();
    }, wait);
  };

  // Start
  h.onStatus('connecting');
  connect();

  // ---- cancel / cleanup (unmount or next turn) ----
  return () => {
    closedByUser = true;
    clearAll(c);
    clearTimers();
    safeClose();
    ws = null;
  };
}
