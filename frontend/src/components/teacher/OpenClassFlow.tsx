// Bridge-3c — 開班 + 揀課 (Teacher Console write surfaces, 掣 1 & 2).
//
// Two server-driven steps in one dialog:
//   1. open a class    POST /api/classes                      {name, class_type, grade_band}
//   2. mount a course  GET  /api/curriculum/catalog
//                      POST /api/classes/{id}/curriculum      {curriculum_id}
//
// The frontend owns no business logic: the catalog (server) decides what may
// be mounted (ready 1..8 only), the mount endpoint expands the eight weeks
// (week 1 active, weeks 2..8 locked) and every failure string is the server's
// own wording (api.ts surfaces `error` verbatim).
//
// Teacher-facing UI is pinned to English (copyEn) — same policy as the rest of
// the teacher console (W3-C).

import { useEffect, useState } from 'react';
import { api, ApiError } from '../../lib/api';
import { copyEn as copy } from '../../lib/i18n';
import type { CurriculumCatalogItem } from '../../lib/types';

type Step = 'class' | 'course';

interface OpenClassFlowProps {
  /** Jump straight to step 2 for a class that exists but has no course yet. */
  mountFor?: { id: string; name: string } | null;
  onClose: () => void;
  /** A class was created — the list should refresh. */
  onClassCreated?: (classId: string) => void;
  /** A course was mounted — the card should refresh. */
  onCourseMounted?: () => void;
}

export function OpenClassFlow({
  mountFor,
  onClose,
  onClassCreated,
  onCourseMounted,
}: OpenClassFlowProps) {
  const [step, setStep] = useState<Step>(mountFor ? 'course' : 'class');
  const [target, setTarget] = useState<{ id: string; name: string } | null>(mountFor ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [mountedTitle, setMountedTitle] = useState('');

  // step 1 — the class form (name / class_type / grade_band)
  const [name, setName] = useState('');
  const [classType, setClassType] = useState<'monthly' | 'workshop'>('monthly');
  const [gradeBand, setGradeBand] = useState('');

  // step 2 — the course picker (dropdown carries curriculum_id only)
  const [catalog, setCatalog] = useState<CurriculumCatalogItem[] | null>(null);
  const [curriculumId, setCurriculumId] = useState('');

  useEffect(() => {
    if (step !== 'course' || catalog !== null) return;
    let alive = true;
    (async () => {
      try {
        const resp = await api.curriculumCatalog();
        if (!alive) return;
        setCatalog(resp.curricula);
        if (resp.curricula.length === 1) setCurriculumId(resp.curricula[0].curriculum_id);
      } catch (err) {
        if (!alive) return;
        setCatalog([]);
        setError(err instanceof ApiError ? err.message : copy.unexpectedError);
      }
    })();
    return () => {
      alive = false;
    };
  }, [step, catalog]);

  const createClass = async () => {
    setBusy(true);
    setError('');
    try {
      const resp = await api.createClass({
        name: name.trim(),
        class_type: classType,
        grade_band: gradeBand || null,
      });
      setTarget({ id: resp.class.id, name: resp.class.name });
      onClassCreated?.(resp.class.id);
      setStep('course'); // 開完直接進下一步
    } catch (err) {
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const mountCourse = async () => {
    if (!target || !curriculumId) return;
    setBusy(true);
    setError('');
    try {
      const resp = await api.mountCurriculum(target.id, curriculumId);
      setMountedTitle(resp.title);
      onCourseMounted?.();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : copy.unexpectedError);
    } finally {
      setBusy(false);
    }
  };

  const fieldCls =
    'mt-1 w-full rounded-lg border border-black/10 bg-white px-3 py-2 text-sm outline-none focus:border-[#00023D]/40';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
      <div className="w-full max-w-md rounded-2xl border border-black/5 bg-white p-6 shadow-lg">
        <h2 className="text-base font-semibold tracking-tight text-[#00023D]">
          {step === 'class' ? copy.newClassTitle : copy.mountTitle}
        </h2>
        {target && (
          <p className="mt-1 text-xs text-black/50">
            {target.name}
          </p>
        )}

        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}

        {step === 'class' ? (
          <div className="mt-4 space-y-3">
            <label className="block text-sm">
              <span className="text-black/70">{copy.classNameLabel}</span>
              <input
                className={fieldCls}
                value={name}
                placeholder={copy.classNamePlaceholder}
                maxLength={60}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="block text-sm">
              <span className="text-black/70">{copy.classTypeLabel}</span>
              <select
                className={fieldCls}
                value={classType}
                onChange={(e) => setClassType(e.target.value as 'monthly' | 'workshop')}
              >
                <option value="monthly">{copy.classTypeMonthly}</option>
                <option value="workshop">{copy.classTypeWorkshop}</option>
              </select>
            </label>
            <label className="block text-sm">
              <span className="text-black/70">{copy.gradeBandLabel}</span>
              <select
                className={fieldCls}
                value={gradeBand}
                onChange={(e) => setGradeBand(e.target.value)}
              >
                <option value="">{copy.gradeBandNone}</option>
                {['P1-P3', 'P4-P6', 'S1-S3'].map((b) => (
                  <option key={b} value={b}>
                    {copy.ageBands[b] ?? b}
                  </option>
                ))}
              </select>
            </label>

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-black/10 px-3 py-2 text-sm text-black/60 hover:bg-black/5"
              >
                {copy.cancelBtn}
              </button>
              <button
                type="button"
                disabled={busy || !name.trim()}
                onClick={createClass}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {copy.createClassBtn}
              </button>
            </div>
          </div>
        ) : mountedTitle ? (
          <div className="mt-4 space-y-3">
            <p className="text-sm text-black/70">{copy.mountCourseLabel}</p>
            <p className="rounded-xl bg-black/5 px-3 py-2 text-sm text-black/70">{mountedTitle}</p>
            <p className="text-xs text-black/50">{copy.mountDoneNote}</p>
            <div className="flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
              >
                {copy.closeBtn}
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-4 space-y-3">
            {catalog === null ? (
              <p className="text-sm text-black/50">{copy.loading}</p>
            ) : catalog.length === 0 ? (
              <p className="text-sm text-black/50">{copy.mountCourseEmpty}</p>
            ) : (
              <label className="block text-sm">
                <span className="text-black/70">{copy.mountCourseLabel}</span>
                <select
                  className={fieldCls}
                  value={curriculumId}
                  onChange={(e) => setCurriculumId(e.target.value)}
                >
                  <option value="">—</option>
                  {catalog.map((c) => (
                    <option key={c.curriculum_id} value={c.curriculum_id}>
                      {c.title}
                    </option>
                  ))}
                </select>
              </label>
            )}

            <div className="flex items-center justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-black/10 px-3 py-2 text-sm text-black/60 hover:bg-black/5"
              >
                {copy.mountLaterBtn}
              </button>
              <button
                type="button"
                disabled={busy || !curriculumId}
                onClick={mountCourse}
                className="rounded-lg bg-[#00023D] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                {copy.mountBtn}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
