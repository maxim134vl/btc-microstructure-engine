import { TONE_DOT_CLASS, TONE_GLOW, TONE_RING_GLOW_CLASS, TONE_RING_TRACK, TONE_STROKE } from "../status";
import type { StatusTone } from "../status";

export function RingGauge({
  value,
  tone,
  size = 92,
  strokeWidth = 8,
  children,
}: {
  value: number;
  tone: StatusTone;
  size?: number;
  strokeWidth?: number;
  children?: React.ReactNode;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const radius = (size - strokeWidth) / 2 - 4;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (clamped / 100) * circumference;
  const center = size / 2;

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={TONE_RING_TRACK[tone]}
          strokeWidth={strokeWidth + 1}
        />
        <circle
          cx={center}
          cy={center}
          r={radius}
          fill="none"
          stroke={TONE_STROKE[tone]}
          strokeWidth={strokeWidth}
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          className={`ring-gauge-progress transition-all duration-500 ease-out ${TONE_RING_GLOW_CLASS[tone]}`}
        />
      </svg>
      {children ? (
        <div className="absolute inset-0 flex items-center justify-center">{children}</div>
      ) : null}
    </div>
  );
}

export function StatusOrb({ tone, size = "lg" }: { tone: StatusTone; size?: "md" | "lg" }) {
  const dim = size === "lg" ? "h-5 w-5" : "h-3.5 w-3.5";

  return <span className={`inline-block rounded-full ${dim} ${TONE_DOT_CLASS[tone]} ${TONE_GLOW[tone]}`} aria-hidden />;
}
