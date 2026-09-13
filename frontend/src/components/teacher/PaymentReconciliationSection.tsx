// Bridge-3e — admin payment reconciliation section (boss decision ②).
//
// Deliberately a SECTION, not a new console: it mounts into the existing
// /teacher container (the 3c surface is already the teacher/admin gateway)
// and renders only what the server says.
//
// Discipline (same as 3b/3c/3d):
//   * UI zero logic — every status flip happens server-side; after a mark the
//     section re-reads the list instead of patching its own copy.
//   * Only the 8-char mask ever reaches the browser; the full uuid exists
//     solely inside the backend.
//   * The note is optional and travels with the mark; the audit line itself
//     is written server-side and never carries an amount.
//   * Repeat marks are idempotent (200, still one row) — the console does not
//     guard against them, it just re-reads.

import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { useLang } from '../../lib/i18n';
import type { AdminPaymentRow, PaymentStatus } from '../../lib/types';

const STATUS_BADGE: Record<PaymentStatus, string> = {
  pending: 'bg-amber-50 text-amber-700 ring-amber-600/20',
  paid: 'bg-emerald-50 text-emerald-700 ring-emerald-600/20',
};

type Filter = PaymentStatus | 'all';

export function PaymentReconciliationSection() {
  const { copy } = useLang();
  const [filter, setFilter] = useState<Filter>('pending');
  const [rows, setRows] = useState<AdminPaymentRow[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(
    async (next: Filter) => {
      setLoading(true);
      try {
        const resp = await api.adminPayments(next === 'all' ? undefined : next);
        setRows(resp.payments);
        setError('');
      } catch (err) {
        setRows([]);
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      } finally {
        setLoading(false);
      }
    },
    [copy.unexpectedError],
  );

  useEffect(() => {
    void load(filter);
  }, [filter, load]);

  const mark = useCallback(
    async (row: AdminPaymentRow, next: PaymentStatus) => {
      setBusy(row.student_id);
      try {
        const note = notes[row.student_id]?.trim();
        if (next === 'paid') {
          await api.adminMarkPaid(row.student_id, note || undefined);
        } else {
          await api.adminMarkPending(row.student_id);
        }
        setNotes((prev) => {
          const rest = { ...prev };
          delete rest[row.student_id];
          return rest;
        });
        setError('');
        await load(filter);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      } finally {
        setBusy('');
      }
    },
    [copy.unexpectedError, filter, load, notes],
  );

  const filterLabel = (f: Filter) =>
    f === 'pending'
      ? copy.paymentStatusPending
      : f === 'paid'
        ? copy.paymentStatusPaid
        : copy.paymentFilterAll;

  return (
    <div className="rounded-2xl border border-black/5 bg-white px-5 py-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-[#00023D]">
            {copy.paymentSectionTitle}
          </h2>
          <p className="mt-0.5 text-xs text-black/40">{copy.paymentSectionSubtitle}</p>
        </div>
        <div className="flex items-center gap-1 rounded-full bg-[#f6f4ef] p-1">
          {(['pending', 'paid', 'all'] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                filter === f ? 'bg-[#00023D] text-white' : 'text-[#00023D]/70'
              }`}
            >
              {filterLabel(f)}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="mt-3 text-xs text-red-700">
          {error}
          <button type="button" onClick={() => void load(filter)} className="ml-2 underline">
            {copy.retry}
          </button>
        </div>
      )}

      {loading && <p className="mt-4 text-xs text-black/40">{copy.loading}</p>}

      {!loading && !error && rows.length === 0 && (
        <p className="mt-4 rounded-xl bg-[#f6f4ef] px-3 py-3 text-xs text-black/50">
          {copy.paymentEmpty}
        </p>
      )}

      {rows.length > 0 && (
        <ul className="mt-3 divide-y divide-black/5">
          {rows.map((row) => (
            <li key={row.student_id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-[#00023D]">{row.first_name}</p>
                <p className="mt-0.5 text-[10px] text-black/40">
                  {row.student_id}
                  {row.marked_at ? ` · ${copy.paymentMarkedAt} ${row.marked_at}` : ''}
                  {row.note ? ` · ${row.note}` : ''}
                </p>
              </div>
              <span
                className={`rounded-full px-2.5 py-0.5 text-[10px] font-medium ring-1 ${STATUS_BADGE[row.status]}`}
              >
                {row.status === 'paid' ? copy.paymentStatusPaid : copy.paymentStatusPending}
              </span>
              {row.status === 'pending' ? (
                <>
                  <input
                    value={notes[row.student_id] ?? ''}
                    onChange={(e) =>
                      setNotes((prev) => ({ ...prev, [row.student_id]: e.target.value }))
                    }
                    placeholder={copy.paymentNotePlaceholder}
                    maxLength={500}
                    className="w-40 rounded-lg border border-black/10 px-2 py-1 text-xs"
                  />
                  <button
                    type="button"
                    disabled={busy === row.student_id}
                    onClick={() => void mark(row, 'paid')}
                    className="rounded-lg bg-[#00023D] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
                  >
                    {copy.paymentMarkPaid}
                  </button>
                </>
              ) : (
                <button
                  type="button"
                  disabled={busy === row.student_id}
                  onClick={() => void mark(row, 'pending')}
                  className="rounded-lg border border-black/10 px-3 py-1.5 text-xs font-medium text-[#00023D] disabled:opacity-50"
                >
                  {copy.paymentMarkPending}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
