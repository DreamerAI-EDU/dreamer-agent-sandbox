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
  PinResetResponse,
  PinVerifyResponse,
  RegisterResponse,
  SafetyEventDetailResponse,
  SafetyEventsResponse,
  SafetyReviewResponse,
  StepUpResponse,
  StudentsResponse,
  User,
} from './types';

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
  consentStatus: () => request<ConsentStatusResponse>('/api/consent/status'),
  consentSign: (docType: string, docVersion: string) =>
    request<{ ok: true; doc_type: string }>('/api/consent/sign', {
      body: { doc_type: docType, doc_version: docVersion },
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
  inviteConfirm: (token: string, payload: { password: string; privacy_policy: boolean; media_consent: boolean }) =>
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
};
