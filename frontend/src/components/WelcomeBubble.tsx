// PR-B — first-visit welcome bubble on the empty chat state.
//
// Pure presentational: the parent (ChatPage) composes the localised text,
// this component only frames it with the Dibi avatar so it reads like a real
// first message. It never talks to the WS stream — no turn, no session, no
// audit event (same zero-pollution bar as PR-A).

import { Dibi } from './Dibi';

interface WelcomeBubbleProps {
  text: string;
  accent: string;
}

export function WelcomeBubble({ text, accent }: WelcomeBubbleProps) {
  return (
    <div className="mx-auto mt-6 flex w-full max-w-md items-start gap-3 text-left">
      <div className="shrink-0">
        <Dibi size={44} accent={accent} />
      </div>
      <div className="rounded-3xl rounded-tl-md border border-white/10 bg-white/10 px-5 py-3 text-sm font-medium leading-relaxed text-white/90">
        {text}
      </div>
    </div>
  );
}
