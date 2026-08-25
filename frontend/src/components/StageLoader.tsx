import { useEffect, useState } from 'react';
import type { BandTheme, Lang } from '../lib/mock';
import { stageNote } from '../lib/stageMap';
import { Dibi } from './Dibi';

export interface ActiveStage {
  stage: string;
  done: boolean;
}

interface Props {
  stages: ActiveStage[];
  theme: BandTheme;
  lang: Lang;
}

// Staged loading: LLM round-trips run 56–100s, so kids watch Dibi climb
// the ladder while named stages tick over — never a dead spinner.
export function StageLoader({ stages, theme, lang }: Props) {
  const [dots, setDots] = useState(1);

  useEffect(() => {
    const t = setInterval(() => setDots((d) => (d % 3) + 1), 500);
    return () => clearInterval(t);
  }, []);

  const title = lang === 'en' ? 'Dibi is thinking' : lang === 'hk' ? 'Dibi 諗緊嘢' : 'Dibi 思考中';

  return (
    <div className="flex items-start gap-3" role="status" aria-live="polite">
      <div className="mt-1">
        <Dibi size={44} accent={theme.accent} climbing wiggle />
      </div>
      <div className="min-w-0">
        <p className="font-bold text-white">
          {title}
          <span className="inline-block w-6 text-left">{'.'.repeat(dots)}</span>
        </p>
        <ol className="mt-2 space-y-1.5">
          {stages.map((s, i) => (
            <li
              key={i}
              className={`flex items-center gap-2 text-sm transition-opacity duration-300 ${
                s.done ? 'opacity-40' : 'opacity-100'
              }`}
            >
              <span
                className={`inline-block h-2.5 w-2.5 rounded-full ${s.done ? 'bg-white/70' : 'animate-pulse'}`}
                style={s.done ? undefined : { backgroundColor: theme.accent, boxShadow: `0 0 8px ${theme.accent}` }}
                aria-hidden
              />
              <span className={s.done ? 'text-white/60 line-through' : 'text-white'}>{stageNote(s.stage, lang)}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}
