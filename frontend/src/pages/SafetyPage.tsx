// W2 PR#6 — teacher/admin safety review page.
// Full event detail requires a fresh step-up (server-enforced). The
// server's `error` wording is shown verbatim.

import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, ApiError } from '../lib/api';
import { useLang } from '../lib/i18n';
import type { SafetyEvent, SafetyEventDetail, User } from '../lib/types';
import { AppShell } from '../components/AppShell';
import { StepUpDialog } from '../components/StepUpDialog';

export function SafetyPage() {
  const { copy } = useLang();
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);
  const [events, setEvents] = useState<SafetyEvent[]>([]);
  const [unreviewedOnly, setUnreviewedOnly] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [stepUpOpen, setStepUpOpen] = useState(false);
  const [pendingEventId, setPendingEventId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SafetyEventDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [markingId, setMarkingId] = useState<string | null>(null);
  const [markError, setMarkError] = useState('');

  const loadEvents = useCallback(
    async (unreviewed: boolean) => {
      try {
        const me = await api.me();
        if (me.user.role === 'parent') {
          navigate('/home', { replace: true });
          return;
        }
        setUser(me.user);
        const resp = await api.safetyEvents(unreviewed);
        setEvents(resp.events);
        setLoadError('');
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          navigate('/login', { replace: true });
          return;
        }
        setLoadError(err instanceof ApiError ? err.message : copy.unexpectedError);
      }
    },
    [copy.unexpectedError, navigate],
  );

  useEffect(() => {
    void loadEvents(unreviewedOnly);
  }, [loadEvents, unreviewedOnly]);

  const openDetail = (eventId: string) => {
    setPendingEventId(eventId);
    setDetail(null);
    setDetailError('');
    setStepUpOpen(true);
  };

  const fetchDetail = async () => {
    if (!pendingEventId) return;
    setStepUpOpen(false);
    try {
      const resp = await api.safetyEventDetail(pendingEventId);
      setDetail(resp.event);
      setDetailError('');
    } catch (err) {
      if (err instanceof ApiError && err.message === '需要重新驗證密碼') {
        // Step-up window expired between dialogs — ask again.
        setStepUpOpen(true);
        return;
      }
      setDetailError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setPendingEventId(null);
    }
  };

  const markReviewed = async (eventId: string) => {
    if (markingId) return;
    setMarkingId(eventId);
    setMarkError('');
    try {
      await api.safetyReview(eventId);
      await loadEvents(unreviewedOnly);
      if (detail && detail.event_id === eventId) {
        setDetail({ ...detail, reviewed: true });
      }
    } catch (err) {
      setMarkError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setMarkingId(null);
    }
  };

  if (!user && !loadError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef]">
        <p className="text-sm text-black/50">{copy.loading}</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#f6f4ef] p-4">
        <div className="w-full max-w-sm rounded-2xl border border-black/5 bg-white p-8 text-center shadow-sm">
          <p className="text-sm text-red-600">{loadError}</p>
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="mt-4 rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
          >
            {copy.loginBtn}
          </button>
        </div>
      </div>
    );
  }

  return (
    <AppShell user={user}>
      <div className="mx-auto max-w-3xl">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">{copy.safetyTitle}</h1>
            <p className="mt-1 text-sm text-black/50">{copy.safetySubtitle}</p>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={unreviewedOnly}
              onChange={(e) => setUnreviewedOnly(e.target.checked)}
              className="h-4 w-4 accent-black"
            />
            {copy.safetyUnreviewedOnly}
          </label>
        </div>

        {loadError && <p className="mt-4 text-sm text-red-600">{loadError}</p>}
        {markError && <p className="mt-4 text-sm text-red-600">{markError}</p>}

        {events.length === 0 ? (
          <p className="mt-8 rounded-2xl border border-dashed border-black/10 p-8 text-center text-sm text-black/50">
            {copy.safetyEmpty}
          </p>
        ) : (
          <ul className="mt-6 space-y-3">
            {events.map((event) => (
              <li
                key={event.event_id}
                className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-base font-semibold">{event.student_first_name}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          event.reviewed ? 'bg-black/5 text-black/50' : 'bg-amber-100 text-amber-800'
                        }`}
                      >
                        {event.reviewed ? copy.safetyReviewed : copy.safetyUnreviewed}
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-black/50">
                      <span>
                        {copy.safetyType}: {event.event_type}
                      </span>
                      <span>
                        {copy.safetySeverity}: {event.severity}
                      </span>
                      <span>{formatTime(event.created_at)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => openDetail(event.event_id)}
                      className="rounded-lg border border-black/10 px-3 py-1.5 text-sm hover:bg-black/5"
                    >
                      {copy.safetyView}
                    </button>
                    {!event.reviewed && (
                      <button
                        type="button"
                        disabled={markingId === event.event_id}
                        onClick={() => markReviewed(event.event_id)}
                        className="rounded-lg bg-black px-3 py-1.5 text-sm text-white disabled:opacity-40"
                      >
                        {markingId === event.event_id ? copy.loading : copy.safetyMarkReviewed}
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <StepUpDialog open={stepUpOpen} onClose={() => setStepUpOpen(false)} onVerified={fetchDetail} />

      {detail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="max-h-[85vh] w-full max-w-lg overflow-y-auto rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold">{copy.safetyDetail}</h2>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-black/50">
              <span>{detail.student_first_name}</span>
              <span>
                {copy.safetyType}: {detail.event_type}
              </span>
              <span>
                {copy.safetySeverity}: {detail.severity}
              </span>
              <span>{formatTime(detail.created_at)}</span>
              {detail.matched_rule && <span>rule: {detail.matched_rule}</span>}
            </div>
            <div className="mt-4">
              <p className="text-xs font-medium text-black/50">{copy.safetyRaw}</p>
              <blockquote className="mt-1 rounded-xl bg-black/5 p-4 text-sm whitespace-pre-wrap">
                {detail.raw_input}
              </blockquote>
            </div>
            {detailError && <p className="mt-3 text-sm text-red-600">{detailError}</p>}
            <div className="mt-5 flex justify-end gap-2">
              {!detail.reviewed && (
                <button
                  type="button"
                  disabled={markingId === detail.event_id}
                  onClick={() => markReviewed(detail.event_id)}
                  className="rounded-lg bg-black px-3 py-2 text-sm text-white disabled:opacity-40"
                >
                  {markingId === detail.event_id ? copy.loading : copy.safetyMarkReviewed}
                </button>
              )}
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="rounded-lg border border-black/10 px-3 py-2 text-sm hover:bg-black/5"
              >
                {copy.safetyClose}
              </button>
            </div>
          </div>
        </div>
      )}
    </AppShell>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
