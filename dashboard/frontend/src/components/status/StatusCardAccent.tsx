import { TONE_ACCENT_BAR, TONE_KPI_WASH, TONE_STRIPE } from "./visual";
import type { ResolvedStatus, StatusTone } from "./types";

export function StatusCardAccent({ tone }: { tone: StatusTone }) {
  return (
    <>
      <div className={`ops-kpi-wash ${TONE_KPI_WASH[tone]}`} aria-hidden />
      <div className={`relative h-[3px] w-full bg-gradient-to-r ${TONE_ACCENT_BAR[tone]}`} />
    </>
  );
}

export function StatusCardAccentFromStatus({ status }: { status: ResolvedStatus }) {
  return <StatusCardAccent tone={status.tone} />;
}

export function statusStripeClass(tone: StatusTone): string {
  return TONE_STRIPE[tone];
}
