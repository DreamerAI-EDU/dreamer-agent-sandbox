// W2 PR#6 — REST client for the real backend.
//
// Same-origin calls through the vite dev proxy (localhost:8001) or the
// production Caddy reverse proxy, so the HttpOnly session cookie is sent
// automatically. Every POST carries X-Requested-With (CSRF header) EXCEPT
// the invite confirm call, which the backend exempts by design
// (mock-mapping §1 / brief §2.3).
//
// Error discipline (brief §3): the frontend never invents its own wording —
// the server's `error` field is shown verbatim.

import type {
  ClassPendingResponse,
  ClassesResponse,
  ConsentDocsResponse,
  ConsentStatusResponse,
  InviteConfirmResponse,
  InvitePublic,
  LoginResponse,
  MeResponse,
  ParentCurriculumResponse,
  PinResetResponse,
  PinVerifyResponse,
  RegisterResponse,
  SafetyEventDetailResponse,
  SafetyEventsResponse,
  SafetyReviewResponse,
  StepUpResponse,
  StudentsResponse,
  StudentCurriculumResponse,
  User,
} from './types';
import type { ParentPeriod, ParentReportEnvelope } from './parentTypes';
import type {
  TeacherClassProgressResponse,
  TeacherStudentProgressResponse,
} from './teacherTypes';
import type {
  KidPortfolioResponse,
  ParentPortfolioResponse,
  ShareCard,
} from './portfolioTypes';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: unknown;
  csrf?: boolean; // default true for POST; invite confirm passes false
  csrfOnGet?: boolean; // W3-B: parent report GET must carry X-Requested-With too
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = options.method ?? (options.body === undefined ? 'GET' : 'POST');
  const headers: Record<string, string> = {};
  let body: string | undefined;
  if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }
  if (method === 'POST' && (options.csrf ?? true)) {
    headers['X-Requested-With'] = 'XMLHttpRequest';
  }
  if (method === 'GET' && options.csrfOnGet) {
    headers['X-Requested-With'] = 'XMLHttpRequest';
  }

  let resp: Response;
  try {
    resp = await fetch(path, {
      method,
      headers,
      body,
      credentials: 'include',
    });
  } catch {
    throw new ApiError(0, '網路連線失敗，請稍後再試');
  }

  let data: unknown = null;
  try {
    data = await resp.json();
  } catch {
    // Non-JSON body (rare) — fall through to status-based handling.
  }

  if (!resp.ok) {
    const serverError =
      data && typeof data === 'object' && 'error' in data
        ? String((data as { error: unknown }).error)
        : '';
    throw new ApiError(resp.status, serverError || `請求失敗 (${resp.status})`);
  }
  return data as T;
}

export const api = {
  me: () => request<MeResponse>('/api/auth/me'),
  login: (email: string, password: string) =>
    request<LoginResponse>('/api/auth/login', { body: { email, password } }),
  // W4 PR-D forgot-password: unauthenticated public endpoints (CSRF header on).
  forgotPassword: (email: string) =>
    request<{ ok: true }>('/api/auth/forgot-password', { body: { email } }),
  resetPassword: (token: string, password: string) =>
    request<{ ok: true }>('/api/auth/reset-password', { body: { token, password } }),
  logout: () => request<{ ok: true }>('/api/auth/logout', { body: {} }),
  register: (inviteCode: string, email: string, password: string) =>
    request<RegisterResponse>('/api/auth/register', {
      body: { invite_code: inviteCode, email, password },
    }),
  verifyEmail: (token: string) =>
    request<{ user: User }>('/api/auth/verify-email', { body: { token } }),
  stepUp: (password: string) =>
    request<StepUpResponse>('/api/auth/step-up', { body: { password } }),

  consentDocs: () => request<ConsentDocsResponse>('/api/consent/docs'),
  consentStatus: (studentId?: string) =>
    request<ConsentStatusResponse>(
      studentId
        ? `/api/consent/status?student=${encodeURIComponent(studentId)}`
        : '/api/consent/status',
    ),
  consentSign: (docType: string, docVersion: string) =>
    request<{ ok: true; doc_type: string }>('/api/consent/sign', {
      body: { doc_type: docType, doc_version: docVersion },
    }),
  // W6 PR-E: per-child withdrawal — the dashboard only holds the 8-char
  // masked Student.id; the backend resolves it inside the parent's
  // reachable set (auth/api.py _consent_resolve_student).
  consentWithdraw: (docType: string, studentId?: string) =>
    request<{ ok: true }>('/api/consent/withdraw', {
      body: studentId
        ? { doc_type: docType, student_id: studentId }
        : { doc_type: docType },
    }),

  students: () => request<StudentsResponse>('/api/students'),
  pinVerify: (maskId: string, pin: string) =>
    request<PinVerifyResponse>(`/api/students/${maskId}/pin-verify`, { body: { pin } }),
  pinReset: (maskId: string, pin?: string) =>
    request<PinResetResponse>(`/api/students/${maskId}/pin-reset`, {
      body: pin ? { pin } : {},
    }),

  invitePublic: (token: string) =>
    request<InvitePublic>(`/api/invites/${token}`, { method: 'GET' }),
  inviteConfirm: (token: string, payload: { password: string; privacy_policy: boolean; chat_consent: boolean; media_consent: boolean }) =>
    request<InviteConfirmResponse>(`/api/invites/${token}/confirm`, {
      body: payload,
      csrf: false, // backend-exempt; do NOT send X-Requested-With
    }),

  // W3-C teacher console (read-only)
  classes: () => request<ClassesResponse>('/api/classes'),
  classPending: (classId: string) =>
    request<ClassPendingResponse>(`/api/classes/${classId}/pending`),

  safetyEvents: (unreviewedOnly: boolean) =>
    request<SafetyEventsResponse>(
      `/api/teacher/safety-events${unreviewedOnly ? '?reviewed=false' : ''}`,
    ),
  safetyEventDetail: (eventId: string) =>
    request<SafetyEventDetailResponse>(`/api/teacher/safety-events/${eventId}`),
  safetyReview: (eventId: string) =>
    request<SafetyReviewResponse>(`/api/teacher/safety-events/${eventId}/review`, { body: {} }),

  // W3-B parent dashboard
  parentReport: (studentId: string, period: ParentPeriod) =>
    request<ParentReportEnvelope>(
      `/api/parent/report?student_id=${encodeURIComponent(studentId)}&period=${period}`,
      { csrfOnGet: true }, // instruction: parent report GET also carries X-Requested-With
    ),

  // W3-B step 3 teacher progress lens
  teacherClassProgress: (classId: string) =>
    request<TeacherClassProgressResponse>(
      `/api/teacher/classes/${encodeURIComponent(classId)}/progress`,
      { csrfOnGet: true },
    ),
  // identifier is the 8-char mask prefix (backend resolves it); full uuid
  // never enters the URL.
  teacherStudentProgress: (identifier: string, period: ParentPeriod) =>
    request<TeacherStudentProgressResponse>(
      `/api/teacher/student/${encodeURIComponent(identifier)}/progress?period=${period}`,
      { csrfOnGet: true },
    ),

  // W4 PR-A portfolio surfaces (GET; backend session gate only)
  // kid-facing portfolio of the PIN-unlocked child (?student= mask/full id,
  // resolved inside the acting parent's reachable set).
  kidPortfolio: (identifier: string) =>
    request<KidPortfolioResponse>(
      `/api/student/portfolio?student=${encodeURIComponent(identifier)}`,
    ),
  // Bridge-3a — kid "Week X / 8" badge (GET; same acting-parent gate as
  // kidPortfolio). A 'none' state is a normal 200, not an error: hide the
  // badge. Errors carry the server wording verbatim, but the chat header
  // stays silent on them (a badge must never scare a child).
  studentCurriculum: (identifier: string) =>
    request<StudentCurriculumResponse>(
      `/api/student/curriculum?student=${encodeURIComponent(identifier)}`,
    ),
  // Bridge-3b — parent 8-week course map (GET; parent session + own child
  // only — the backend answers 403 for another family's child). `state:none`
  // is a normal 200 (no class / nothing mounted): the grid renders its neutral
  // message, not an error. Same gate vocabulary as kidPortfolio.
  parentCurriculum: (identifier: string) =>
    request<ParentCurriculumResponse>(
      `/api/parent/curriculum?student_id=${encodeURIComponent(identifier)}`,
    ),
  parentPortfolio: (studentId: string) =>
    request<ParentPortfolioResponse>(
      `/api/parent/portfolio/${encodeURIComponent(studentId)}`,
    ),
  parentShareCard: (studentId: string, itemId: string) =>
    request<ShareCard>(
      `/api/parent/portfolio/${encodeURIComponent(studentId)}/share_card/${encodeURIComponent(itemId)}`,
    ),
};
