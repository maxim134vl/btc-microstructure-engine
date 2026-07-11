import { TONE_DOT_CLASS } from "./visual";
import type { StatusTone } from "./types";

export function StatusDot({
  tone,
  className = "",
  pulse = false,
}: {
  tone: StatusTone;
  className?: string;
  pulse?: boolean;
}) {
  return (
    <span className={`relative inline-flex shrink-0 ${className}`} aria-hidden>
      {pulse ? (
        <span className={`status-dot-ping status-dot-ping--${tone} absolute inset-0 animate-ping rounded-full`} />
      ) : null}
      <span className={`${TONE_DOT_CLASS[tone]} relative inline-block h-full w-full rounded-full`} />
    </span>
  );
}
