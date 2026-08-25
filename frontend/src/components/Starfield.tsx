import { useMemo } from 'react';

// Deterministic PRNG so the sky is identical on every load
function mulberry32(seed: number) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Star {
  left: string;
  top: string;
  size: number;
  opacity: number;
  twinkle: boolean;
  delay: string;
}

// Deep-space backdrop matching dreamer-aiedu.net: navy #1a1a2e + scattered stars.
export function Starfield() {
  const stars = useMemo<Star[]>(() => {
    const rnd = mulberry32(20260823);
    return Array.from({ length: 110 }, () => {
      const big = rnd() > 0.85;
      return {
        left: `${(rnd() * 100).toFixed(2)}%`,
        top: `${(rnd() * 100).toFixed(2)}%`,
        size: big ? 2.5 : rnd() > 0.5 ? 1.5 : 1,
        opacity: 0.35 + rnd() * 0.65,
        twinkle: rnd() > 0.72,
        delay: `${(rnd() * 4).toFixed(2)}s`,
      };
    });
  }, []);

  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden="true">
      {/* soft nebula glows */}
      <div
        className="absolute -left-40 top-[-15%] h-[34rem] w-[34rem] rounded-full opacity-25"
        style={{ background: 'radial-gradient(circle, #4b5bd6 0%, transparent 65%)' }}
      />
      <div
        className="absolute -right-48 bottom-[-20%] h-[38rem] w-[38rem] rounded-full opacity-20"
        style={{ background: 'radial-gradient(circle, #7c5cd6 0%, transparent 65%)' }}
      />
      {stars.map((s, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-white"
          style={{
            left: s.left,
            top: s.top,
            width: s.size,
            height: s.size,
            opacity: s.opacity,
            animation: s.twinkle ? `twinkle 3.5s ease-in-out ${s.delay} infinite` : undefined,
          }}
        />
      ))}
    </div>
  );
}
