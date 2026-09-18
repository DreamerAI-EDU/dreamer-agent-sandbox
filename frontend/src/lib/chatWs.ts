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
  message_id?: unknown;   // PR-C item 4 — ack 收據含 message_id（TS2339 fix-forward）
  status?: unknown;       // PR-C item 4 — ack 含 status（'dup' 等）
  turn_state?: unknown;   // PR-C item 4 — dup-ack 含 turn_state（'completed' 判 turn-lost）
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
// PR-C item 1 — app-level heartbeat: client pings every 30s, relay answers
// locally (keeps intermediate proxies from idling the socket out).
const PING_INTERVAL_MS = 30000;
// PR-C item 4 — immediate-receipt ack: the relay acks a turn frame as soon as
// it arrives. If no ack within 10s the client re-sends the SAME message_id
// (max 2 resends, then network fail). The ack means "relay got it", never
// "engine answered".
const ACK_TIMEOUT_MS = 10000;
const ACK_MAX_RESENDS = 2;

export interface WsStreamContext {
  student?: string; // 8-char mask prefix, from ?student= (full ids never enter state)
  /** mount-resume: true when this stream is a fresh page-load resume attempt (F5 reload), not a same-instance reconnect */
  resumeFromMount?: boolean;
}

function delayMs(attempt: number): number {
  const base = Math.min(1000 * 2 ** (attempt - 1), 16000);
  return base + Math.floor(Math.random() * JITTER_MS);
}

function getStr(v: unknown): string {
  return typeof v === 'string' ? v : '';
}

// ---- P4 §4.1(7): engine-session persistence --------------------------------
// One engine session per student, owned by the server-side relay map; the
// client only needs to remember WHICH session it was routed to so a reload or
// the next turn resumes the SAME engine session ("Dibi 記得昨日嘅嘢"). Keyed
// by the 8-char mask — the only student identifier the client ever holds —
// never by a full id (red-line 8).
const SESSION_KEY_PREFIX = 'dreamer.ws_chat.session.';

function sessionStorageKey(student: string): string {
  return `${SESSION_KEY_PREFIX}${student}`;
}

function loadPersistedSession(student: string): string {
  try {
    return localStorage.getItem(sessionStorageKey(student)) ?? '';
  } catch {
    return ''; // storage disabled (private mode) — start fresh each stream
  }
}

function savePersistedSession(student: string, sessionId: string): void {
  if (!sessionId) return;
  try {
    localStorage.setItem(sessionStorageKey(student), sessionId);
  } catch {
    /* storage disabled — continuity degrades to per-stream, never crashes */
  }
}

// ---- PR-C item 2 — in-flight turn marker (sessionStorage, per tab) -------
// sessionStorage is the precise model for "同 tab F5 要 resume、新 tab 唔帶舊
// turn": it survives a reload in the SAME tab but is never copied to a new
// tab, so a fresh tab starts a new turn while a F5 mid-turn resumes the old
// one. Set when a turn frame goes out, cleared on done / fail / quiet finish.
const INFLIGHT_KEY_PREFIX = 'dreamer.ws_chat.inflight.';

function inflightKey(student: string): string {
  return `${INFLIGHT_KEY_PREFIX}${student}`;
}

function loadInflight(student: string): boolean {
  try {
    return window.sessionStorage.getItem(inflightKey(student)) === '1';
  } catch {
    return false; // storage disabled — fall back to startTurn each time
  }
}

/** Public read-only view of the in-flight marker — used by ChatPage's
 *  mount-resume effect (F5 reload mid-turn) to decide whether to open a
 *  silent resume stream. Never mutated here. */
export function hasInflightTurn(student: string): boolean {
  return loadInflight(student);
}

function setInflight(student: string): void {
  try {
    window.sessionStorage.setItem(inflightKey(student), '1');
  } catch {
    /* storage disabled — degrade to per-stream, never crashes */
  }
}

function clearInflight(student: string): void {
  try {
    window.sessionStorage.removeItem(inflightKey(student));
  } catch {
    /* storage disabled */
  }
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
  // 窗 5 retry 觀察用（log only，零行為改動）：done-seen 同 frame count 係
  // 判讀 ③（client↔relay 交付斷點）嘅兩個關鍵信號。
  let frameCount = 0;
  let lastFrameType = '';
  let currentTurnId = '';

  // Turn state (one session ⇒ one connection ⇒ one turn at a time)
  // P4 §4.1(7): seed from the persisted engine session ('' = first ever
  // turn / storage unavailable); the relay blanket-rewrites it regardless.
  let sessionId = loadPersistedSession(student);
  let lastSeq = 0;
  const chunks: string[] = [];
  const sources: ChatSource[] = [];
  const live: ActiveStage[] = [];

  // Reconnect resume markers
  let resumeHangTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  // PR-C item 3 — send queue: frames sent while the socket is not OPEN are
  // queued and flushed on open (fixes the silent drop on send-before-reconnect).
  const queue: string[] = [];
  // PR-C item 4 — ack-wait state for the current turn frame
  let resendTimer: ReturnType<typeof setTimeout> | null = null;
  let pendingAckMid = '';
  let resendCount = 0;
  // PR-C item 1 — heartbeat timer
  let pingTimer: ReturnType<typeof setInterval> | null = null;

  // 觀察 log — DevTools filter: [chat-ws][observe]
  const logObservation = (phase: string) => {
    console.info(
      `[chat-ws][observe] ${phase} done-seen=${doneSeen} frames=${frameCount} result-seen=${resultSeen} last-frame=${lastFrameType || '-'} last-seq=${lastSeq} attempt=${attempt} session=${sessionId.slice(0, 8) || '-'} turn=${currentTurnId || '-'}`,
    );
  };

  const clearTimers = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (resumeHangTimer) clearTimeout(resumeHangTimer);
    if (resendTimer) clearTimeout(resendTimer);
    if (pingTimer) clearInterval(pingTimer);
    reconnectTimer = null;
    resumeHangTimer = null;
    resendTimer = null;
    pingTimer = null;
  };

  const fail = (kind: KidErrorKind) => {
    if (c.cancelled) return;
    logObservation(`fail:${kind}`);
    // Turn is over from the client's perspective — no further automatic
    // retries; the user retries manually which opens a fresh stream.
    closedByUser = true;
    clearTimers();
    clearInflight(student);
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
    logObservation('quiet-finish');
    closedByUser = true;
    clearTimers();
    clearInflight(student);
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

  // PR-C item 4 — per-turn client id. crypto.randomUUID when available
  // (secure context), deterministic-ish fallback otherwise.
  const newMessageId = (): string => {
    try {
      if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
      }
    } catch {
      /* fall through */
    }
    return `m-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  };

  const sendFrame = (payload: Record<string, unknown>): boolean => {
    const text = JSON.stringify(payload);
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(text);
      return true;
    }
    // PR-C item 3 — never drop: park the frame and flush on open.
    queue.push(text);
    return false;
  };

  const flushQueue = (): boolean => {
    if (ws?.readyState !== WebSocket.OPEN) return false;
    let flushed = false;
    while (queue.length > 0) {
      const text = queue.shift();
      if (text !== undefined) {
        ws.send(text);
        flushed = true;
      }
    }
    return flushed;
  };

  // PR-C item 1 — app-level heartbeat while the socket is live.
  const startPing = () => {
    if (pingTimer) clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping' }));
      }
    }, PING_INTERVAL_MS);
  };

  const startTurn = () => {
    // Capability frame — contract keys ONLY (learning #14: an unknown config
    // key silently drops DeepTutor into stub mode). language rides as the
    // top-level field per docs/phase2-websocket.md. session_id carries the
    // persisted engine session (P4 §4.1(7)) — the relay blanket-rewrites it
    // to its own map, so a stale/missing value can never cross students.
    const messageId = newMessageId();
    logObservation('turn-start');
    setInflight(student);
    pendingAckMid = messageId;
    resendCount = 0;
    const frame = {
      type: 'message',
      capability: 'chat',
      content: input,
      language: langCode,
      session_id: sessionId, // persisted engine session; '' → server assigns
      message_id: messageId, // PR-C item 4 — relay acks this immediately
    };
    sendFrame(frame);
    armResend(frame);
  };

  const armResend = (frame: Record<string, unknown>) => {
    if (resendTimer) clearTimeout(resendTimer);
    resendTimer = setTimeout(() => {
      if (c.cancelled) return;
      if (pendingAckMid !== frame.message_id) return; // ack already arrived
      if (resendCount >= ACK_MAX_RESENDS) {
        console.error('[chat-ws] no ack after resends — network fail');
        clearInflight(student);
        fail('network');
        return;
      }
      resendCount += 1;
      console.warn(
        `[chat-ws] resend message ${String(frame.message_id)} (${resendCount}/${ACK_MAX_RESENDS})`,
      );
      sendFrame(frame); // same message_id — relay dedups if the first one landed
      armResend(frame);
    }, ACK_TIMEOUT_MS);
  };

  const resumeTurn = () => {
    // Reconnect: ask the server to replay the tail of the still-running turn.
    logObservation('resume');
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
    logObservation('result');
    const payload = buildPayload();
    if (!payload.content) {
      console.warn('[chat-ws] result with empty content — turn-lost path');
      fail('turn-lost');
      return;
    }
    h.onResult(payload);
  };

  const handleFrame = (raw: unknown) => {
    frameCount += 1;
    if (!raw || typeof raw !== 'object') {
      lastFrameType = '<non-object>';
      console.warn('[chat-ws] non-object frame dropped');
      return;
    }
    const ev = raw as RawFrame;
    const type = getStr(ev.type);
    lastFrameType = type || '<untyped>';
    const tid = getStr(ev.turn_id);
    if (tid) currentTurnId = tid;
    const seq = getNum(ev.seq);
    if (seq > lastSeq) lastSeq = seq;
    const meta = ev.metadata && typeof ev.metadata === 'object' ? ev.metadata : undefined;

    switch (type) {
      case 'session': {
        sessionId = getStr(ev.session_id) || getStr(pick(meta ?? {}, 'session_id'));
        // P4 §4.1(7): persist the engine-assigned session so the next turn /
        // a reload resumes it. Never cleared here — the server-side map owns
        // invalidation (engine reject self-heals the relay's row).
        savePersistedSession(student, sessionId);
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
        logObservation('done');
        clearResumeHangWatch();
        // PR-C item 2 — the turn is over: clear the in-flight marker so the
        // next send (even after a F5) starts a fresh turn instead of resuming.
        clearInflight(student);
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
      case 'ack': {
        // PR-C item 4 — immediate-receipt receipt. Clears the 10s resend
        // watch; a dup-ack means the relay already owns this message_id and
        // reports the current turn state instead of re-opening it.
        const mid = getStr(ev.message_id);
        const status = getStr(ev.status);
        if (mid && resendTimer && pendingAckMid === mid) {
          clearTimeout(resendTimer);
          resendTimer = null;
          pendingAckMid = '';
        }
        if (status === 'dup') {
          const turnState = getStr(ev.turn_state);
          console.warn('[chat-ws] dup-ack', mid, turnState);
          if (turnState === 'completed' && !resultSeen) {
            // The relay finished this turn already but nothing reached us —
            // degrade exactly like a resume that replays nothing.
            fail('turn-lost');
          }
        }
        break;
      }
      case 'pong': {
        // PR-C item 1 — heartbeat echo, nothing to render.
        break;
      }
      case 'error': {
        const code = getStr(ev.error_code);
        const msg = getStr(ev.content) || getStr(pick(meta ?? {}, 'error'));
        console.error('[chat-ws] server error frame', code, msg);
        clearResumeHangWatch();
        // PR-C item 6 — session_closed means the relay has no replay for this
        // session (completed-but-lost or never existed). Mount-resume split:
        // a fresh page-load that finds no replayable turn must NOT vanish
        // quietly — the kid just came back mid-question, so surface the
        // gentle resume-lost banner. Same-instance reconnect keeps the old
        // quiet finish (nobody navigated away mid-answer).
        if (code === 'session_closed') {
          if (ctx.resumeFromMount) {
            fail('resume-lost');
          } else {
            finishQuietly();
          }
          break;
        }
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
      startPing();
      // PR-C item 3 — queued frames go out first (a turn frame already sent
      // means "start that turn", never double-start).
      if (flushQueue()) return;
      // PR-C item 2 — in-flight marker decides resume vs start: a turn is
      // still running in THIS tab → resume its tail; otherwise start fresh
      // even if a persisted session id exists (the A-scenario bug).
      if (loadInflight(student)) resumeTurn();
      else startTurn();
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
      logObservation('closed-without-done');
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
    clearInflight(student);
    safeClose();
    ws = null;
  };
}
