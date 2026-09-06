// W3-B — Period tabs: weekly / cycle / journey.
//
// Pure presentational control. ParentDashboard owns the active period state
// and calls onChange when a tab is clicked.

import type { ParentPeriod } from '../../lib/parentTypes';

interface PeriodTabsProps {
  active: ParentPeriod;
  onChange: (period: ParentPeriod) => void;
}

const TABS: { value: ParentPeriod; title: string; hint: string }[] = [
  { value: 'weekly', title: '週報', hint: '本週摘要' },
  { value: 'cycle', title: '週期報告', hint: '8 週主報告' },
  { value: 'journey', title: '成長旅程', hint: '全歷程回顧' },
];

export function PeriodTabs({ active, onChange }: PeriodTabsProps) {
  return (
    <div className="inline-flex rounded-full border border-black/10 bg-white p-1">
      {TABS.map((tab) => {
        const isActive = tab.value === active;
        return (
          <button
            key={tab.value}
            type="button"
            onClick={() => onChange(tab.value)}
            title={tab.hint}
            className={`rounded-full px-4 py-1.5 text-sm transition-colors ${
              isActive
                ? 'bg-[#00023D] text-white'
                : 'text-black/60 hover:bg-[#00023D]/15'
            }`}
          >
            {tab.title}
          </button>
        );
      })}
    </div>
  );
}
