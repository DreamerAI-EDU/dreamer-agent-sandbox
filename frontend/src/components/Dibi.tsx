import mascot from '../assets/dreamer-mascot.png';

interface Props {
  size?: number;     // px, roundel diameter
  accent: string;    // band accent — halo + thinking ring colour
  climbing?: boolean; // thinking state: accent ring sweeps around the roundel
  wiggle?: boolean;
}

// Mascot = the official Dreamer circled A-ladder logo on a white roundel.
// While "climbing" (waiting on the LLM), an accent-coloured ring sweeps
// around it — the thinking signal, using the official mark unmodified.
export function Dibi({ size = 40, accent, climbing = false, wiggle = false }: Props) {
  return (
    <div
      className={`relative shrink-0 ${wiggle ? 'animate-[wiggle_1s_ease-in-out_infinite]' : ''}`}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {climbing && (
        <div
          className="absolute rounded-full animate-spin"
          style={{
            inset: -3,
            background: `conic-gradient(${accent} 0%, transparent 55%)`,
            animationDuration: '1.4s',
          }}
        />
      )}
      <img
        src={mascot}
        alt=""
        className="relative h-full w-full rounded-full"
        style={{ boxShadow: `0 0 ${size / 2}px ${accent}55` }}
        draggable={false}
      />
    </div>
  );
}
