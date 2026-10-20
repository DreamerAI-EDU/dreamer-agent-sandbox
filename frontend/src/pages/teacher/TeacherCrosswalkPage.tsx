// PR-5 A6 — crosswalk one-pager (/teacher/crosswalk), teacher role only.
//
// Renders §6 of the signed design book VERBATIM from lib/teacherCrosswalk.ts.
// No re-wording, no summarising, no invented extra columns: the strings in
// that module are anchor-tested character-for-character, and this component
// only lays them out. The frame's guard already bounced non-teachers, and the
// backend answers 403 on every /api/teacher/* route behind it.

import { TeacherConsoleFrame } from './TeacherConsoleFrame';
import {
  CROSSWALK_COLUMNS,
  CROSSWALK_PURPOSE,
  CROSSWALK_ROWS,
  CROSSWALK_STANDARD_ANSWER,
  CROSSWALK_TITLE,
} from '../../lib/teacherCrosswalk';

export function TeacherCrosswalkPage() {
  return (
    <TeacherConsoleFrame title="Crosswalk 一頁紙" subtitle="內部專用，永不出家長版">
      <div
        className="rounded-2xl border border-black/5 bg-white p-5 shadow-sm"
        data-testid="crosswalk-page"
      >
        <h2 className="text-base font-bold text-[#00023D]">{CROSSWALK_TITLE}</h2>
        <p className="mt-2 text-xs text-black/50">{CROSSWALK_PURPOSE}</p>

        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left text-xs">
            <thead>
              <tr className="bg-black/[0.03] text-[11px] font-bold text-black/50">
                <th className="border border-black/10 px-3 py-2">
                  {CROSSWALK_COLUMNS.parentSees}
                </th>
                <th className="border border-black/10 px-3 py-2">
                  {CROSSWALK_COLUMNS.internal}
                </th>
                <th className="border border-black/10 px-3 py-2">
                  {CROSSWALK_COLUMNS.oralBridge}
                </th>
              </tr>
            </thead>
            <tbody data-testid="crosswalk-rows">
              {CROSSWALK_ROWS.map((row, idx) => (
                <tr key={`${row.parentSees}-${idx}`} className="align-top">
                  <td className="border border-black/10 px-3 py-2 font-bold text-[#00023D]">
                    {row.parentSees}
                  </td>
                  <td className="border border-black/10 px-3 py-2 text-black/60">
                    {row.internal}
                  </td>
                  <td className="border border-black/10 px-3 py-2 text-black/70">
                    {row.oralBridge}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-4 border-t border-black/5 pt-3 text-xs leading-relaxed text-black/70">
          {CROSSWALK_STANDARD_ANSWER}
        </p>
      </div>
    </TeacherConsoleFrame>
  );
}
