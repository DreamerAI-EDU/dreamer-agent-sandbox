// W2 PR#6 — real-backend API contract types.
// Mirrors auth/api.py response shapes (verified against main 93e216d).
// student_id is always the 8-char mask prefix; full ids never enter the
// frontend state / URL / localStorage.

export type Role = 'parent' | 'teacher' | 'admin';

export interface User {
  id: string;
  email: string;
  role: Role;
  email_verified: boolean;
}

export interface MeResponse {
  user: User;
}

export interface LoginResponse {
  user: User;
  consent_required: boolean;
  missing_consent: string[];
}

// W3-C teacher console
export interface ClassSummary {
  id: string;
  name: string;
  join_code: string;
  class_type: 'monthly' | 'workshop';
  grade_band: string | null;
  is_one_on_one: number;
  created_at: string;
  pending_count: number;
  confirmed_count: number;
}

export interface ClassesResponse {
  classes: ClassSummary[];
}

export interface PendingStudent {
  student_id: string;
  first_name: string;
  age_band: string;
  lang_code: string;
}

export interface ClassPendingResponse {
  class_id: string;
  pending: PendingStudent[];
}

export interface RegisterResponse {
  user: User;
}

export interface ConsentDoc {
  doc_type: string;
  current_version: string;
  required: boolean;
  /** Roles this document applies to (W6 PR-F role scope). */
  roles: string[];
  title_zh: string;
  title_en: string;
}

export interface ConsentDocsResponse {
  documents: Record<string, ConsentDoc>;
}

export interface ConsentStatusEntry {
  doc_type: string;
  current_version: string;
  required: boolean;
  /** Roles this document applies to (W6 PR-F role scope). */
  roles: string[];
  title_zh: string;
  title_en: string;
  status: 'unsigned' | 'agreed' | 'withdrawn';
  doc_version: string | null;
}

export interface ConsentStatusResponse {
  documents: Record<string, ConsentStatusEntry>;
}

export interface Student {
  id: string; // 8-char mask prefix only
  first_name: string;
  age_band: string;
  lang_code: string;
}

export interface StudentsResponse {
  students: Student[];
}

export interface PinVerifyResponse {
  ok: true;
}

export interface PinResetResponse {
  ok: true;
  pin?: string; // present only when the server generated the PIN
}

export interface InvitePublic {
  first_name: string;
  age_band: string;
  lang_code: string;
  parent_email: string;
}

export interface InviteConfirmResponse {
  ok: true;
  user: { id: string; email: string };
}

export interface SafetyEvent {
  event_id: string;
  created_at: string;
  event_type: string;
  severity: string;
  reviewed: boolean;
  student_first_name: string;
}

export interface SafetyEventsResponse {
  events: SafetyEvent[];
}

export interface SafetyEventDetail {
  event_id: string;
  created_at: string;
  event_type: string;
  severity: string;
  raw_input: string;
  matched_rule?: string | null;
  age_band: string;
  lang_code: string;
  reviewed: boolean;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  student_first_name: string;
  student_id: string; // mask prefix
}

export interface SafetyEventDetailResponse {
  event: SafetyEventDetail;
}

export interface SafetyReviewResponse {
  ok: true;
  event_id: string;
  reviewed: true;
}

export interface StepUpResponse {
  ok: true;
  expires_at: string;
}

// Bridge-3a — kid "Week X / 8" badge (GET /api/student/curriculum).
//
// `unit_title` is the authored kid-facing string the backend resolved from
// topic_metadata; the frontend renders it verbatim and NEVER translates a
// topic_id itself (label_soften tradition / North Star #3).
//
// `state` vocabulary:
//   'active'    → the class has one open week: show "Week {week_index} / 8"
//   'completed' → all 8 weeks done: show "8/8 · 完成" (Bridge-2 course_completed)
//   'none'      → no class / no mounted course / non-linear rows: HIDE the badge
//                 (neutral, never an error — the child surface must not 500)
export type StudentWeekState = 'active' | 'completed' | 'none';

export interface StudentCurriculumResponse {
  state: StudentWeekState;
  week_index: number | null; // null iff state === 'none'
  total_weeks: number;
  unit_title: string; // backend-authored, kid-facing; '' when unknown
}

// Bridge-3b — parent 8-week course map (GET /api/parent/curriculum).
//
// One row per week of the mounted course, in week order. `title` is authored
// server-side from topic_metadata and rendered verbatim — the parent grid
// never translates a topic_id itself (label_soften tradition / North Star #3).
//
// `mastery_pct` is the raw rolling 0..1 value (MasteryBar scales it). It is
// `null` when that week has NO data — the UI must show 未有數據/No data yet
// and NEVER 0% (neutral, no invented progress). A stored 0.0 is real data.
//
// `state`: 'active' (one week open) / 'completed' (all 8 done) / 'none'
// (no class, no mounted course, non-linear rows → show the neutral message,
// never an error).
export type ParentWeekStatus = 'locked' | 'active' | 'completed';

export interface ParentCurriculumWeek {
  week_no: number;
  title: string;
  status: ParentWeekStatus;
  mastery_pct: number | null; // raw 0..1; null = no data for that week
}

export interface ParentCurriculumResponse {
  course_title: string; // backend-authored; '' when unknown
  current_week: number | null; // null iff state === 'none'
  total_weeks: number;
  state: StudentWeekState;
  weeks: ParentCurriculumWeek[]; // [] iff state === 'none'
}

// ---------------------------------------------------------------------------
// Bridge-3c — Teacher Console: open a class, mount a course, read progress.
// Mirrors auth/api.py handlers + auth/curriculum.py class_curriculum_state.
// The console renders these values verbatim: every status flip, the 8-week
// expansion and the linear lock all happen server-side (ruling: UI zero logic).
// ---------------------------------------------------------------------------

/** One mountable course from GET /api/curriculum/catalog (ready 1..8 only). */
export interface CurriculumCatalogItem {
  curriculum_id: string;
  /** Authored course title — render verbatim, never translate. */
  title: string;
  week_count: number;
  ready: boolean;
}

export interface CurriculumCatalogResponse {
  curricula: CurriculumCatalogItem[];
}

/** POST /api/classes -> 201. The class starts with NO mounted course. */
export interface CreateClassResponse {
  class: {
    id: string;
    name: string;
    join_code: string;
    class_type: 'monthly' | 'workshop';
    grade_band: string | null;
    is_one_on_one: number;
  };
}

export type ClassWeekStatus = 'locked' | 'active' | 'completed';

/** "none" = nothing mounted yet (neutral 200, not an error). */
export type ClassCourseState = 'none' | 'active' | 'completed';

export interface ClassCurriculumRow {
  week_no: number;
  /** Internal teaching id — carried for identification, never rendered. */
  topic_id: string;
  /** Authored week title — render verbatim, never translate. */
  title: string;
  status: ClassWeekStatus;
  /** Class-average mastery, raw 0..1 scale; null when that week has no data. */
  mastery_pct: number | null;
}

/** GET /api/classes/{id}/curriculum — the 進度 card source of truth. */
export interface ClassCurriculumResponse {
  class_id: string;
  course_title: string;
  state: ClassCourseState;
  current_week: number | null; // null iff state === 'none'
  total_weeks: number;
  mastery_scope: 'class';
  weeks: ClassCurriculumRow[];
}

/** POST /api/classes/{id}/curriculum -> 201 (server expanded the 8 weeks). */
export interface MountCurriculumResponse {
  class_id: string;
  curriculum_id: string;
  title: string;
  week_count: number;
  weeks: {
    topic_id: string;
    week_no: number;
    status: ClassWeekStatus;
    activated_at: string | null;
  }[];
}

