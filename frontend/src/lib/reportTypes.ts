// PR-5 — Teacher report console + parent read-only report contracts.
//
// Field names verified against the SHIPPED backend (auth/api.py
// handle_teacher_score_put / handle_teacher_reports_list /
// handle_teacher_report_detail / handle_teacher_report_update /
// _teacher_report_decide / handle_parent_reports, plus
// auth/report_store._row_to_dict). No field here is invented:
//   * list / detail rows are `_teacher_report_view(row)` = _row_to_dict +
//     draft_url (+ payload on the detail route only)
//   * `payload` is the stored single-language envelope; its `report` object
//     additionally carries `dimension_descriptors` (PR-4, band × lang)
//   * the edit route takes {edits: [{field, before, after}], payload_patch}
//     and answers the refreshed row — teacher_edits is append-only server-side

import type { ParentReportInner } from './parentTypes';

export type ReportStatus =
  | 'pending_review'
  | 'approved'
  | 'rejected'
  | 'superseded';

export const REPORT_STATUSES: ReportStatus[] = [
  'pending_review',
  'approved',
  'rejected',
  'superseded',
];

/** PR-4 — dimension code -> the descriptor sentence for this band × lang. */
export type DimensionDescriptors = Record<string, string>;

/** PR-6 §A1-4 — dimension code -> BOTH language cells of the same 144-table
 *  cell ({en, zh}), derived server-side from the stored scores. The web detail
 *  route and the S2 PDF both read this, so the wording has one source. */
export type DimensionDescriptorPairs = Record<string, { en: string; zh: string }>;

export interface ReportPayload {
  content: string;
  mode: string;
  lang_code: string;
  age_band: string | null;
  /** B3: internal envelope slot kept server-side; the teacher console shows
   *  the frozen friendly name instead (parentReportCopy.bandLabel). */
  report: ParentReportInner & { dimension_descriptors?: DimensionDescriptors };
}

export interface ReportRow {
  report_id: string;
  version: number;
  student_id: string;
  class_id: string;
  week_from: number;
  week_to: number;
  status: ReportStatus;
  lang_code: string;
  age_band: string;
  scores: Record<string, number | null>;
  review: Record<string, unknown>;
  cost_summary: Record<string, unknown>;
  generated_by: string;
  created_at: string;
  updated_at: string;
  approved_at: string;
  published_at: string;
  teacher_edits_count: number;
  draft_url: string;
}

/** GET /api/teacher/reports/{id} — row + stored envelope. */
export interface ReportDetail extends ReportRow {
  payload: ReportPayload;
}

export interface TeacherReportsResponse {
  ok: true;
  reports: ReportRow[];
  counts: Record<ReportStatus, number>;
}

export interface ReportDetailResponse extends ReportDetail {
  ok: true;
}

/** 409 one-pending gate — carries the blocking draft's link (§4.4). */
export interface PendingConflict {
  error: string;
  report_id: string;
  version: number;
  status: ReportStatus;
  draft_url: string;
}

export interface ScoreWriteResponse {
  ok: true;
  student_id: string; // 8-char mask
  week_no: number;
  skill_code: string;
  status: string;
  assessment_log_id: string;
}

/** GET /api/parent/reports — list entry (payload-free summary row). */
export interface ParentReportRow {
  report_id: string;
  version: number;
  student_id: string; // 8-char mask
  week_from: number;
  week_to: number;
  /** Always 'approved' — the backend lists approved rows only (§B1). */
  status: 'approved';
  lang_code: string;
  age_band: string;
  published_at: string;
}

export interface ParentReportsResponse {
  reports: ParentReportRow[];
  count: number;
}

/** GET /api/parent/reports?student_id=…&report_id=… — one produced body. */
export interface ParentReportDetailResponse {
  report: {
    report_id: string;
    version: number;
    week_from: number;
    week_to: number;
    status: 'approved';
    lang_code: string;
    age_band: string;
    published_at: string;
    payload: ReportPayload;
    /** PR-6 S1 — present on the detail route; absent (not empty) for legacy
     *  rows whose band owns no descriptor cell. */
    descriptor_pairs?: DimensionDescriptorPairs;
  };
}

/** 4D rollup row used by the scoring form (A1) and the review view (A4). */
export interface DimensionScoreRow {
  code: string;
  name: string;
  score: number | null;
}

export const SCORE_MAX = 3;
export const EVIDENCE_MAX_CHARS = 200;
export const WEEK_MIN = 1;
export const WEEK_MAX = 8;
