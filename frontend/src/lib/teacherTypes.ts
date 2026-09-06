// W3-B 步骤 3 — Teacher Progress Lens API contract types.
//
// Mirrors the REAL backend responses (auth/api.py + auth/reports.py, shipped
// in the same W3-B step-1 commit as the parent report):
//   GET /api/teacher/classes/{classId}/progress
//   GET /api/teacher/student/{studentId}/progress
//
// Field-name notes (verified against auth/reports.py, NOT the step-3
// instruction sketch §4/§5 which used older placeholder names):
//   - class row fields:  student_id (FULL uuid — trusted teacher console
//     surface; the UI derives the 8-char mask for deep links and never
//     renders the full id), display_name, age_band, lang_code,
//     media_consent, last_activity_at, last_label_kid, mastery_pct,
//     updated_at
//   - class progress wraps { class, stats, students } (stats carries
//     student_count / pending_count / average_mastery_pct)
//   - student progress wraps { student, report, assessment_history } where
//     report is the canonical ParentReportEnvelope (same-source parity) and
//     assessment_history is the sanitised label timeline (internal labels /
//     confidence / rubric ids never leave the server).
//
// mastery_pct / average_mastery_pct stay on the backend 0..1 scale — display
// code multiplies by 100 (MasteryBar does this internally).

import type { ParentPeriod, ParentReportEnvelope } from './parentTypes';

export type TeacherConsent = 'unsigned' | 'agreed' | 'withdrawn';

export interface TeacherClassProgressClassInfo {
  id: string;
  name: string;
  class_type: string;
  grade_band: string | null;
  is_one_on_one: boolean;
}

export interface TeacherClassProgressStats {
  student_count: number;
  pending_count: number;
  /** Mean of latest-snapshot mastery over confirmed students, 0..1; null when no snapshots. */
  average_mastery_pct: number | null;
}

export interface TeacherClassStudent {
  /** Full uuid — teacher console surface; never rendered. Derive mask via teacherMaskOf(). */
  student_id: string;
  display_name: string; // profile.first_name only (B24)
  age_band: string | null;
  lang_code: string;
  media_consent: TeacherConsent;
  last_activity_at: string | null; // ISO; latest assessment/session ts
  /** Backend kid-facing softened label — render verbatim, never translate. */
  last_label_kid: string;
  /** Latest snapshot mastery, raw rolling value 0..1; null = no snapshot yet. */
  mastery_pct: number | null;
  updated_at: string | null;
}

export interface TeacherClassProgressResponse {
  class: TeacherClassProgressClassInfo;
  stats: TeacherClassProgressStats;
  students: TeacherClassStudent[];
}

export interface TeacherStudentSummary {
  student_id: string; // full uuid — not rendered
  display_name: string;
  age_band: string | null;
  lang_code: string;
  media_consent: TeacherConsent;
}

export interface TeacherAssessmentHistoryEntry {
  date: string; // yyyy-mm-dd
  topic_id: string;
  subject: string;
  mode: string;
  /** Parent-facing softened label — render verbatim (teacher-side sanitised). */
  label_parent: string;
}

export interface TeacherStudentProgressResponse {
  student: TeacherStudentSummary;
  /** Canonical Parent Report envelope (same data as the parent lens). */
  report: ParentReportEnvelope;
  assessment_history: TeacherAssessmentHistoryEntry[];
}

/** 8-char mask for deep links / API identifier; full uuids stay off the URL. */
export function teacherMaskOf(studentId: string): string {
  if (!studentId) return '';
  return studentId.length > 8 ? studentId.slice(0, 8) : studentId;
}

/** Short date label for a teacher console (English, locale-agnostic). */
export function fmtActivityDate(iso: string | null | undefined): string {
  if (!iso) return '';
  const day = iso.slice(0, 10); // yyyy-mm-dd
  return day;
}

/** Relative English label: "Today" / "Yesterday" / "5d ago" / absolute date. */
export function fmtRelativeDay(iso: string | null | undefined): string {
  if (!iso) return '—';
  const day = iso.slice(0, 10);
  const then = new Date(`${day}T00:00:00`);
  if (Number.isNaN(then.getTime())) return day;
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diffDays = Math.round((today.getTime() - then.getTime()) / 86400000);
  if (diffDays <= 0) return 'Today';
  if (diffDays === 1) return 'Yesterday';
  if (diffDays < 30) return `${diffDays}d ago`;
  return day;
}

export const TEACHER_PERIODS: ParentPeriod[] = ['weekly', 'cycle', 'journey'];
