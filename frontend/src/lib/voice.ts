// c1-13b Phase 1 — voice input client (P1-P3 trial).
//
// The gate lives server-side: this module only asks whether a mic may exist
// (GET /api/voice/config) and posts one clip (POST /api/voice/transcribe).
// The transcript that comes back is placed in the composer by the caller —
// it is NEVER auto-submitted, so a mis-heard word cannot be sent by itself.
//
// Error discipline matches lib/api.ts: the server's `error` wording is shown
// verbatim; the client never invents its own.

import { ApiError } from './api';

export type VoiceConfig = {
  enabled: boolean;
  max_seconds?: number;
  max_upload_bytes?: number;
  daily_remaining_seconds?: number;
};

export type VoiceTranscript = {
  text: string;
  seconds_used: number;
  daily_remaining_seconds: number;
};

/** Whether this kid may see a mic button (401 → disabled, not an error). */
export async function fetchVoiceConfig(): Promise<VoiceConfig> {
  let resp: Response;
  try {
    resp = await fetch('/api/voice/config', { credentials: 'include' });
  } catch {
    return { enabled: false };
  }
  if (!resp.ok) {
    return { enabled: false };
  }
  try {
    const data = (await resp.json()) as VoiceConfig;
    // `enabled` last on purpose: TS2783 rejects a duplicated key in one
    // literal, and the spread could otherwise hand back a non-boolean.
    return { ...data, enabled: Boolean(data?.enabled) };
  } catch {
    return { enabled: false };
  }
}

/** Send one clip; the server bills the meters and returns the transcript. */
export async function transcribeClip(
  clip: Blob,
  durationMs: number,
  lang: string,
): Promise<VoiceTranscript> {
  const form = new FormData();
  form.append('audio', clip, 'clip');
  form.append('duration_ms', String(Math.round(durationMs)));
  form.append('lang', lang);

  let resp: Response;
  try {
    resp = await fetch('/api/voice/transcribe', {
      method: 'POST',
      // CSRF: same custom-header scheme as every other SPA POST.
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: form,
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, '網絡連線失敗，請稍後再試');
  }

  let data: unknown = null;
  try {
    data = await resp.json();
  } catch {
    // non-JSON body: fall through to the status-based wording
  }
  if (!resp.ok) {
    const serverError =
      data && typeof data === 'object' && 'error' in data
        ? String((data as { error: unknown }).error)
        : '';
    throw new ApiError(resp.status, serverError || '語音辨識暫時用唔到，可以打字問我');
  }
  return data as VoiceTranscript;
}

/**
 * Pick a container the recorder supports (Safari only does mp4/aac; Chrome
 * and Firefox do webm/opus). An empty string lets the browser choose.
 */
export function pickMimeType(): string {
  if (typeof MediaRecorder === 'undefined') return '';
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/mp4',
    'audio/ogg;codecs=opus',
  ];
  for (const type of candidates) {
    if (MediaRecorder.isTypeSupported(type)) return type;
  }
  return '';
}

export type RecorderHandle = {
  stop: () => void;
};

/**
 * Start recording, auto-stop at `maxSeconds`, resolve with the clip + its
 * measured length. Push-to-talk: the caller stops it on release too.
 */
export async function startRecording(
  maxSeconds: number,
  onAutoStop: (clip: Blob, durationMs: number) => void,
): Promise<RecorderHandle> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks: BlobPart[] = [];
  const startedAt = Date.now();

  const release = () => stream.getTracks().forEach((track) => track.stop());

  recorder.addEventListener('dataavailable', (event) => {
    if (event.data && event.data.size > 0) chunks.push(event.data);
  });
  recorder.addEventListener('stop', () => {
    const durationMs = Date.now() - startedAt;
    release();
    if (chunks.length === 0) return;
    onAutoStop(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }), durationMs);
  });

  const timer = window.setTimeout(() => {
    if (recorder.state !== 'inactive') recorder.stop();
  }, Math.max(1, maxSeconds) * 1000);

  recorder.start();

  return {
    stop: () => {
      window.clearTimeout(timer);
      if (recorder.state !== 'inactive') recorder.stop();
      else release();
    },
  };
}
