// W3-B — Parent Dashboard API contract types.
//
// Mirrors the REAL backend response of GET /api/parent/report (envelope +
// report, per docs/phase6-schemas.md §1, landed in commit d7b6810
// "W3-B parent report + teacher progress API (step 1)").
//
// NOTE on W3-B-步驟2-指令 §6 "ParentReport" sketch:
// The instruction's §6 flattened shape (top-level mastery_pct /
// mastery_delta / kid_label / topic_summary / cost_summary) is an older
// phase-6 snapshot. The shipped backend (and locked docs/phase6-schemas.md)
// returns the SEVEN-FIELD ENVELOPE below instead:
//   content / mode / lang_code / age_band / kid_label / citations /
//   cost_summary  +  report: { ... }
// The components render from this envelope:
//   - mastery_pct / mastery_delta live PER-TOPIC in report.topics[]
//     (scale 0..1 — display code multiplies by 100)
//   - kid-facing copy (report.topics[].last_label_parent) comes verbatim
//     from the backend D3 mapping (front-end never translates)
//   - total_duration_seconds lives in report.summary (null = no data)
//   - cost_summary is the envelope-level {status, total_tokens}

export type ParentPeriod = 'weekly' | 'cycle' | 'journey';
export type ParentVariant = 'first_steps' | 'standard';

export const PARENT_PERIODS: ParentPeriod[] = ['weekly', 'cycle', 'journey'];

export interface ParentCostSummary {
  status: 'ok' | 'no_data';
  total_tokens: number;
}

export interface ParentModeDistribution {
  DIRECT: number;
  CONTEXTUAL: number;
  HYBRID: number;
}

export interface ParentReportSummary {
  session_count: number;
  /** Seconds actually recorded. null (not 0) means "no data" — never fake a 0. */
  total_duration_seconds: number | null;
  topics_touched: number;
  mode_distribution: ParentModeDistribution;
}

export interface ParentReportTopicEvidence {
  date: string;
  label_parent: string;
  evidence_text: string;
}

export interface ParentReportTopic {
  topic_id: string;
  subject: string;
  /** Rolling-average mastery, scale 0..1 — render as pct * 100. */
  mastery_pct: number;
  /** Period delta, scale 0..1 (may be negative) — render as points * 100. */
  mastery_delta: number;
  attempt_count: number;
  last_label_internal?: string; // stripped by backend for privacy; defensive only
  /** Backend D3 parent-facing copy — use verbatim, never re-translate. */
  last_label_parent: string;
  streak: number;
  recent_evidence: ParentReportTopicEvidence[];
}

export interface ParentTimelineEntry {
  date: string;
  sessions: number;
  modes: string[];
}

export interface ParentBaseline {
  date: string;
  topic_id: string;
  subject: string;
  label_parent: string;
  confidence: number; // 0..1
}

export interface ParentRoadmapStep {
  topic_id: string;
  topic_name: string;
  reason: 'prerequisite_not_strong' | 'prerequisite_untouched' | 'continue_practice' | string;
  /** Backend locale-ready copy — use verbatim. */
  action: string;
}

export interface ParentSafetyAlert {
  type: string;
  severity: string;
  ts: string;
  event_ref: string;
}

export interface ParentReportPeriod {
  type: ParentPeriod;
  from: string | null;
  to: string | null;
  days: number;
}

export interface ParentReportPortfolioHighlight {
  id: string;
  title: string;
}

export interface ParentReportInner {
  student_id: string; // 8-char mask prefix only
  variant: ParentVariant;
  period: ParentReportPeriod;
  summary: ParentReportSummary;
  topics: ParentReportTopic[];
  activity_timeline: ParentTimelineEntry[];
  baseline: ParentBaseline | null;
  roadmap: ParentRoadmapStep[] | null;
  portfolio_highlights: ParentReportPortfolioHighlight[];
  safety_alerts?: ParentSafetyAlert[];
}

/** GET /api/parent/report — full envelope returned by auth/api.py handle_parent_report. */
export interface ParentReportEnvelope {
  /** Narrative digest paragraph (parent-facing tone). */
  content: string;
  mode: 'parent_report';
  lang_code: string;
  age_band: string | null;
  kid_label: string | null;
  citations: unknown[];
  cost_summary: ParentCostSummary;
  report: ParentReportInner;
}

/** Mastery helpers — backend stores 0..1; UI wants 0..100. */
export function masteryToPercent(mastery: number | null | undefined): number | null {
  if (mastery === null || mastery === undefined) return null;
  return Math.round(mastery * 100);
}

export function deltaToPoints(delta: number | null | undefined): number | null {
  if (delta === null || delta === undefined) return null;
  return Math.round(delta * 100);
}

export function formatDuration(seconds: number | null): string | null {
  if (seconds === null || seconds === undefined) return null;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins <= 0) return `${secs} 秒`;
  return `${mins} 分 ${secs} 秒`;
}
