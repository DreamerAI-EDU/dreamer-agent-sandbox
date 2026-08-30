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

export interface ConsentDoc {
  doc_type: string;
  current_version: string;
  required: boolean;
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
