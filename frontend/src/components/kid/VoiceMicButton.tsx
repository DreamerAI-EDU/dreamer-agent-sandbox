// c1-13b Phase 1 — push-to-talk mic button (P1-P3 trial).
//
// Push-to-talk is NON-NEGOTIABLE: recording runs only while the button is
// held, and it stops by itself at the server-provided segment cap. On release
// the clip is transcribed and handed back to the composer as TEXT — the child
// presses send themselves, so a mis-heard word never goes out on its own.
//
// The button is rendered by the page only when /api/voice/config says the
// gate is open (flag + band + signed consent + budget meters).

import { useCallback, useEffect, useRef, useState } from 'react';

import {
  startRecording,
  transcribeClip,
  type RecorderHandle,
} from '../../lib/voice';

type VoiceLabels = {
  start: string;
  stop: string;
  busy: string;
  micDenied: string;
  failed: string;
  empty: string;
};

const LABELS: Record<string, VoiceLabels> = {
  en: {
    start: 'Hold to talk',
    stop: 'Release to stop',
    busy: 'Listening…',
    micDenied: 'No microphone access — ask a grown-up.',
    failed: 'Voice is not working right now — you can type instead.',
    empty: "I didn't hear anything — try again?",
  },
  hk: {
    start: '撳住講',
    stop: '放手就停',
    busy: '聽緊…',
    micDenied: '用唔到麥克風，要大人幫手開權限。',
    failed: '語音暫時用唔到，可以打字問我。',
    empty: '聽唔到聲，再試一次？',
  },
  cn: {
    start: '按住说',
    stop: '松开就停',
    busy: '听着呢…',
    micDenied: '用不了麦克风，请大人帮忙开权限。',
    failed: '语音暂时用不了，可以打字问我。',
    empty: '没听到声音，再试一次？',
  },
};

export function VoiceMicButton({
  lang,
  maxSeconds,
  disabled = false,
  onTranscript,
}: {
  lang: string;
  maxSeconds: number;
  disabled?: boolean;
  onTranscript: (text: string) => void;
}) {
  const labels = LABELS[lang] ?? LABELS.en;
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const handleRef = useRef<RecorderHandle | null>(null);

  // Unmount while recording must not leave the OS mic light on.
  useEffect(
    () => () => {
      handleRef.current?.stop();
      handleRef.current = null;
    },
    [],
  );

  const finish = useCallback(
    async (clip: Blob, durationMs: number) => {
      setRecording(false);
      setBusy(true);
      try {
        const result = await transcribeClip(clip, durationMs, lang);
        if (result.text.trim()) {
          onTranscript(result.text.trim());
          setNotice(null);
        } else {
          setNotice(labels.empty);
        }
      } catch (error) {
        // Server wording wins (lib/api discipline); typed fallback otherwise.
        setNotice(error instanceof Error && error.message ? error.message : labels.failed);
      } finally {
        setBusy(false);
      }
    },
    [lang, labels.empty, labels.failed, onTranscript],
  );

  const begin = useCallback(async () => {
    if (disabled || busy || recording) return;
    setNotice(null);
    try {
      handleRef.current = await startRecording(maxSeconds, (clip, durationMs) => {
        void finish(clip, durationMs);
      });
      setRecording(true);
    } catch {
      setRecording(false);
      setNotice(labels.micDenied);
    }
  }, [busy, disabled, finish, labels.micDenied, maxSeconds, recording]);

  const end = useCallback(() => {
    handleRef.current?.stop();
    handleRef.current = null;
  }, []);

  return (
    <div className="flex shrink-0 flex-col items-center gap-1">
      <button
        type="button"
        disabled={disabled || busy}
        onPointerDown={(event) => {
          event.preventDefault();
          void begin();
        }}
        onPointerUp={end}
        onPointerLeave={recording ? end : undefined}
        onPointerCancel={end}
        aria-label={recording ? labels.stop : labels.start}
        aria-pressed={recording}
        className={`shrink-0 rounded-full px-5 py-3 font-black text-white transition-colors disabled:opacity-40 ${
          recording
            ? 'bg-[#ef4444] hover:bg-[#dc2626]'
            : 'border border-white/25 bg-white/10 hover:bg-white/20'
        }`}
      >
        {busy ? labels.busy : recording ? labels.stop : labels.start}
      </button>
      {notice && (
        <p role="status" className="max-w-[16rem] text-center text-[11px] text-white/60">
          {notice}
        </p>
      )}
    </div>
  );
}
