import type { ReactNode } from "react";
import { useTranslation } from "../../i18n";
import type { CognitiveEventClass, CognitiveReviewEvent } from "../../types/cognitiveReview";
import { COGNITIVE_EVENT_COLORS } from "../../types/cognitiveReview";
import { formatTime } from "../visual-cognition/chartUtils";

export {
  ChartInlineForm,
  InfoRow,
  InspectorHint,
  InspectorSection,
  ReviewCheckbox,
  WorkflowActionButton,
  WorkflowSection,
  WorkspaceToolbarButton,
} from "../stage1-review/Stage1ReviewChrome";

const REVIEW_STATUS_STYLE: Record<string, { label: string; className: string }> = {
  CORRECT: {
    label: "Verified",
    className: "border-emerald-500/30 bg-emerald-500/10 text-ds-status-healthy",
  },
  INCORRECT: {
    label: "Rejected",
    className: "border-red-500/30 bg-red-500/10 text-ds-status-error",
  },
  UNCERTAIN: {
    label: "Uncertain",
    className: "border-amber-500/30 bg-amber-500/10 text-ds-status-warning",
  },
  UNREVIEWED: {
    label: "Unreviewed",
    className: "border-ds-border bg-ds-surface-secondary/60 text-ds-text-tertiary",
  },
};

export function KpiChip({ label, value, accent }: { label: string; value: string | number; accent?: string }) {
  return (
    <div className="rounded-xl border border-ds-border bg-ds-surface-secondary/50 px-2.5 py-1.5 text-center">
      <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-ds-text-tertiary">{label}</div>
      <div
        className="mt-0.5 font-ds-display text-[14px] font-semibold tabular-nums text-ds-text-primary"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </div>
    </div>
  );
}

export function ReviewStatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  const translated = t(`cognitiveReview.reviewStatus.${status}`);
  const style = REVIEW_STATUS_STYLE[status] ?? {
    label: status,
    className: "border-ds-border bg-ds-surface-secondary/60 text-ds-text-secondary",
  };
  const label = translated.startsWith("cognitiveReview.") ? style.label : translated;
  return (
    <span className={`inline-flex rounded-lg border px-2 py-0.5 text-[10px] font-medium ${style.className}`}>
      {label}
    </span>
  );
}

export function EventClassSwatch({ eventClass, size = 8 }: { eventClass: CognitiveEventClass; size?: number }) {
  return (
    <span
      className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, backgroundColor: COGNITIVE_EVENT_COLORS[eventClass] }}
      aria-hidden
    />
  );
}

export function EventLibraryGroupHeader({
  eventClass,
  label,
  count,
}: {
  eventClass: CognitiveEventClass;
  label: string;
  count: number;
}) {
  return (
    <div className="mb-1.5 flex items-center gap-2 px-0.5">
      <EventClassSwatch eventClass={eventClass} />
      <span className="font-ds-display text-[11px] font-semibold" style={{ color: COGNITIVE_EVENT_COLORS[eventClass] }}>
        {label}
      </span>
      <span className="text-[10px] tabular-nums text-ds-text-tertiary">{count}</span>
    </div>
  );
}

export function EventLibraryItem({
  event,
  active,
  onSelect,
}: {
  event: CognitiveReviewEvent;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`w-full rounded-xl border px-2.5 py-2 text-left transition-colors ${
          active
            ? "border-ds-border bg-ds-surface-secondary ring-1 ring-ds-border"
            : "border-ds-border/70 hover:border-ds-border hover:bg-ds-surface-secondary/60"
        }`}
      >
        <div className="flex items-center gap-2">
          <EventClassSwatch eventClass={event.event_class} size={6} />
          <span className="text-[10px] tabular-nums text-ds-text-tertiary">{formatTime(event.timestamp)}</span>
        </div>
        {event.event_class === "MISSED_EVENT" && event.human_event_class ? (
          <p className="mt-1 line-clamp-1 text-[10px] text-ds-text-secondary">{event.human_event_class}</p>
        ) : null}
        <div className="mt-1.5">
          <ReviewStatusBadge status={event.review_status} />
        </div>
      </button>
    </li>
  );
}

export function CompareEventRow({
  event,
  checked,
  onToggle,
}: {
  event: CognitiveReviewEvent;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-ds-border/70 px-2 py-1.5 text-[10px] transition-colors hover:bg-ds-surface-secondary/50">
      <input type="checkbox" checked={checked} onChange={onToggle} className="rounded border-ds-border" />
      <EventClassSwatch eventClass={event.event_class} size={6} />
      <span className="text-ds-text-primary">{event.display_class}</span>
      <span className="ml-auto text-ds-text-tertiary">{formatTime(event.timestamp)}</span>
    </label>
  );
}

export function InspectorEmpty({ children }: { children: ReactNode }) {
  return <p className="text-[11px] leading-relaxed text-ds-text-tertiary">{children}</p>;
}
