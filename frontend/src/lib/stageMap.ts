// Server stage name → kid-facing note.
// Real stage set is NOT fixed (mock turn 2 has 'guard', turn 1 does not), so the
// map must never crash on unknown stages: StageLoader renders STAGE_MAP[stage]
// resolved through stageNote(), and unknown stages fall back to a generic copy.
// Calibrate keys against the real container's observed stage names after Step 2.
import type { Lang } from './mock';

export const STAGE_MAP: Record<string, Record<Lang, string>> = {
  thinking: { en: 'Reading your question…', hk: '睇緊你條問題…', cn: '正在读你的问题…' },
  retrieval: { en: 'Looking inside the Dreamer library…', hk: '喺 Dreamer 知識庫搵資料…', cn: '正在翻 Dreamer 知识库…' },
  writing: { en: 'Writing an answer just for you…', hk: '寫緊一個專屬答案俾你…', cn: '正在为你写专属答案…' },
  guard: { en: 'Checking the responsible-use rules…', hk: '睇緊負責任使用守則…', cn: '正在检查负责任使用守则…' },
  // Real DeepTutor chat stage names (observed on the real container 2026-09-05)
  exploring: { en: 'Exploring your question…', hk: '探索緊你條問題…', cn: '正在探索你的问题…' },
  responding: { en: 'Writing your answer…', hk: '寫緊你嘅答案…', cn: '正在写你的答案…' },
};

const UNKNOWN_NOTE: Record<Lang, string> = {
  en: 'Working on it…',
  hk: '處理緊…',
  cn: '处理中…',
};

export function stageNote(stage: string, lang: Lang): string {
  return STAGE_MAP[stage]?.[lang] ?? UNKNOWN_NOTE[lang];
}
