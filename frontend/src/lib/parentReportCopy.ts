// PR-5 §三 — FROZEN parent-console copy (single source of truth in the repo).
//
// 施工令 PR-5 (2026-10-20) §三 freezes these strings:
//   * the 3×3 band friendly-name grid (en / zh-HK / zh-CN)
//   * the level names (Exemplary / Achieved / Developing / Not Yet …)
// Anything a parent can read in the report console comes from THIS module,
// or is copied verbatim out of the backend payload (descriptor sentences and
// `last_label_parent` — the front end never translates or edits those).
//
// Anchor test: tests/test_pr5_frozen_copy_anchor.py asserts every string below
// character-for-character against §三 of the signed design book. Edit only
// together with a new 施工令.

/** Report language, keyed by the stored `lang_code` (single language per report). */
export type ReportLang = 'en' | 'zh-hk' | 'zh-cn';

export type BandCode = 'P1-P3' | 'P4-P6' | 'S1-S3';

/** The nine frozen cells of §三. Keys are the internal band codes; the VALUES
 *  are what a parent sees — the raw code itself is never rendered (§B3). */
export const BAND_LABELS: Record<BandCode, Record<ReportLang, string>> = {
  'P1-P3': {
    en: 'Lower Primary (P1–P3)',
    'zh-hk': '小學低年級組（P1–P3）',
    'zh-cn': '小学低年级组（P1–P3）',
  },
  'P4-P6': {
    en: 'Upper Primary (P4–P6)',
    'zh-hk': '小學高年級組（P4–P6）',
    'zh-cn': '小学高年级组（P4–P6）',
  },
  'S1-S3': {
    en: 'Secondary (S1–S3)',
    'zh-hk': '中學組（S1–S3）',
    'zh-cn': '中学组（S1–S3）',
  },
};

/** §三: level names stay the frozen names (0–3). */
export const LEVEL_LABELS: Record<ReportLang, Record<number, string>> = {
  en: { 3: 'Exemplary', 2: 'Achieved', 1: 'Developing', 0: 'Not Yet' },
  'zh-hk': { 3: '出色', 2: '達標', 1: '進展中', 0: '尚未開始' },
  'zh-cn': { 3: '出色', 2: '达标', 1: '进展中', 0: '尚未开始' },
};

/** 4D dimension names — the Dreamer words are the same in every language
 *  (design book §4.2 / §6 "家长版见到" column). */
export const DIMENSIONS: { code: string; name: string }[] = [
  { code: 'DREAM', name: 'Dream' },
  { code: 'DISCOVER', name: 'Discover' },
  { code: 'DESIGN', name: 'Design' },
  { code: 'DELIVER', name: 'Deliver' },
];

/** Console chrome for the parent read-only views (B1 list / B2 detail).
 *  Declared in the PR-5 交付文档「新措辞申报」节 — no other wording allowed. */
export interface ParentReportCopy {
  title: string;
  subtitle: string;
  listTitle: string;
  empty: string;
  loading: string;
  backToList: string;
  openReport: string;
  weekRange: string;
  published: string;
  band: string;
  lang: string;
  version: string;
  summary: string;
  sessions: string;
  topics: string;
  minutes: string;
  narrative: string;
  dimensions: string;
  topicsTitle: string;
  mastery: string;
  evidence: string;
  readOnly: string;
  notFound: string;
}

export const PARENT_REPORT_COPY: Record<ReportLang, ParentReportCopy> = {
  en: {
    title: 'Weekly reports',
    subtitle: 'Read-only view of the reports your teacher has approved.',
    listTitle: 'Approved reports',
    empty: 'No approved report yet. It will appear here once the teacher approves it.',
    loading: 'Loading…',
    backToList: 'Back to the list',
    openReport: 'Open',
    weekRange: 'Weeks',
    published: 'Published',
    band: 'Stage',
    lang: 'Language',
    version: 'Version',
    summary: 'At a glance',
    sessions: 'Learning sessions',
    topics: 'Topics covered',
    minutes: 'Minutes',
    narrative: 'What we saw',
    dimensions: '4 Dimension Evaluation',
    topicsTitle: 'Topic detail',
    mastery: 'Mastery',
    evidence: 'Evidence',
    readOnly: 'Read-only',
    notFound: 'This report is not available.',
  },
  'zh-hk': {
    title: '每週報告',
    subtitle: '只讀檢視老師已批核的報告。',
    listTitle: '已批核報告',
    empty: '暫時未有已批核報告，老師批核後會顯示喺呢度。',
    loading: '載入中…',
    backToList: '返回列表',
    openReport: '查看',
    weekRange: '週次',
    published: '發佈日期',
    band: '階段',
    lang: '語言',
    version: '版本',
    summary: '學習概覽',
    sessions: '學習節數',
    topics: '涵蓋主題',
    minutes: '分鐘',
    narrative: '我哋觀察到',
    dimensions: '4 Dimension Evaluation',
    topicsTitle: '主題詳情',
    mastery: '掌握度',
    evidence: '學習證據',
    readOnly: '只讀',
    notFound: '呢份報告未能顯示。',
  },
  'zh-cn': {
    title: '每周报告',
    subtitle: '只读查看老师已批准的智能报告。',
    listTitle: '已批准报告',
    empty: '暂时没有已批准报告，老师批准后会显示在这里。',
    loading: '加载中…',
    backToList: '返回列表',
    openReport: '查看',
    weekRange: '周次',
    published: '发布日期',
    band: '阶段',
    lang: '语言',
    version: '版本',
    summary: '学习概览',
    sessions: '学习节数',
    topics: '涵盖主题',
    minutes: '分钟',
    narrative: '我们观察到',
    dimensions: '4 Dimension Evaluation',
    topicsTitle: '主题详情',
    mastery: '掌握度',
    evidence: '学习证据',
    readOnly: '只读',
    notFound: '这份报告未能显示。',
  },
};

/** `lang_code` from the payload → one of the three frozen languages. */
export function toReportLang(langCode: string | null | undefined): ReportLang {
  const raw = (langCode ?? '').toLowerCase().replace('_', '-');
  if (raw === 'zh-hk' || raw === 'zh-hant' || raw === 'hk') return 'zh-hk';
  if (raw === 'zh-cn' || raw === 'zh-hans' || raw === 'cn' || raw === 'zh') return 'zh-cn';
  return 'en';
}

/** Internal band code → frozen friendly name. Unknown codes fall back to the
 *  first frozen cell so a legacy band can never leak a raw code to a parent. */
export function bandLabel(band: string | null | undefined, lang: ReportLang): string {
  const code = (band ?? '') as BandCode;
  const grid = BAND_LABELS[code];
  return grid ? grid[lang] : BAND_LABELS['P1-P3'][lang];
}

/** 0–3 → frozen level name. Unknown -> 'Not Yet' cell (never an invented word). */
export function levelLabel(level: number | null | undefined, lang: ReportLang): string {
  if (level === null || level === undefined) return LEVEL_LABELS[lang][0];
  return LEVEL_LABELS[lang][level] ?? LEVEL_LABELS[lang][0];
}
