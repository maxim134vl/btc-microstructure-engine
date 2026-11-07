import type { HealthLevel } from "../types";
import type { AlertSeverity, BehavioralNarrative, Descriptor, MtfAlignmentView, OperatorAlert, RibbonChip } from "../lib/operatorView";
import { descriptorColor } from "../lib/operatorView";

const LEVEL_STYLES: Record<HealthLevel, string> = {
  GREEN: "border-command-green/50 bg-command-green/10 text-ds-status-healthy",
  YELLOW: "border-command-yellow/50 bg-command-yellow/10 text-ds-status-warning",
  RED: "border-command-red/50 bg-command-red/10 text-ds-status-error",
};

const ALERT_STYLES: Record<AlertSeverity, string> = {
  INFO: "border-slate-600/50 text-ds-text-primary",
  WARNING: "border-command-yellow/50 text-ds-status-warning",
  CRITICAL: "border-command-red/50 text-ds-status-error",
};

export function RibbonChipView({ chip }: { chip: RibbonChip }) {
  return (
    <div className={`rounded border px-2.5 py-1.5 ${LEVEL_STYLES[chip.level]}`}>
      <div className="text-[9px] font-semibold tracking-[0.14em] opacity-80">{chip.label}</div>
      <div className="mt-0.5 max-w-[11rem] truncate font-mono text-xs font-medium text-ds-text-primary">{chip.value}</div>
    </div>
  );
}

export function StateBlock({
  label,
  value,
  descriptor,
  large = false,
}: {
  label: string;
  value: string;
  descriptor?: Descriptor;
  large?: boolean;
}) {
  const level = descriptor ? descriptorColor(descriptor) : "GREEN";
  return (
    <div className={`rounded border border-command-border bg-command-bg/40 p-3 ${large ? "col-span-full" : ""}`}>
      <div className="text-[10px] uppercase tracking-[0.12em] text-ds-text-tertiary">{label}</div>
      <div className={`mt-1 font-mono font-semibold text-ds-text-primary ${large ? "text-xl leading-tight" : "text-sm"}`}>{value}</div>
      {descriptor ? (
        <div className={`mt-2 inline-flex rounded border px-2 py-0.5 text-[10px] uppercase ${LEVEL_STYLES[level]}`}>{descriptor}</div>
      ) : null}
    </div>
  );
}

export function NarrativePanel({ narrative }: { narrative: BehavioralNarrative }) {
  return (
    <section className="rounded border border-command-border bg-command-panel">
      <header className="border-b border-command-border px-4 py-3">
        <h2 className="text-base font-semibold tracking-wide text-ds-text-primary">Current Behavioral State</h2>
        <p className="text-[11px] text-ds-text-tertiary">Operator interpretation layer</p>
      </header>
      <div className="grid gap-3 p-4 md:grid-cols-2">
        <StateBlock label="Regime" value={narrative.regime.replace(/_/g, " ")} large />
        <StateBlock label="D1 Structural Bias" value={narrative.d1StructuralBias} descriptor={narrative.runtimeStability === "HEALTHY" ? "STABLE" : "MODERATE"} large />
        <StateBlock label="Active Ontology" value={narrative.activeOntology} descriptor="ACTIVE" />
        <StateBlock label="Auction State" value={narrative.auctionState.replace(/_/g, " ")} />
        <StateBlock label="Contradictions" value={narrative.contradictions} descriptor={narrative.contradictions} />
        <StateBlock label="Reinforcement" value={narrative.reinforcement} descriptor={narrative.reinforcement} />
        <StateBlock label="Transition Risk" value={narrative.transitionRisk} descriptor={narrative.transitionRisk} />
        <StateBlock label="Runtime" value={narrative.runtimeStability} descriptor={narrative.runtimeStability} />
        <StateBlock label="Cognition" value={narrative.cognitionStability} descriptor={narrative.cognitionStability} />
        <StateBlock label="Entropy" value={narrative.entropyState.replace(/_/g, " ")} />
      </div>
    </section>
  );
}

export function D1DominancePanel({ mtf }: { mtf: MtfAlignmentView }) {
  const d1 = mtf.d1;
  return (
    <section className="rounded border-2 border-command-accent/30 bg-command-panel">
      <header className="border-b border-command-border px-4 py-3">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-ds-accent">D1 Structural Anchor</h2>
            <p className="text-[11px] text-ds-text-tertiary">Macro regime context · long-horizon bias</p>
          </div>
          <span className="rounded border border-command-accent/40 px-2 py-1 text-[10px] uppercase text-ds-accent">Primary TF</span>
        </div>
      </header>
      <div className="p-4">
        <div className="mb-4 rounded border border-command-accent/20 bg-command-bg/60 p-4">
          <div className="text-[10px] uppercase tracking-wider text-ds-text-tertiary">Structural bias</div>
          <div className="mt-2 font-mono text-2xl font-semibold leading-tight text-ds-text-primary">
            {d1?.auction_state?.replace(/_/g, " ") ?? "UNKNOWN"}
          </div>
          <div className="mt-2 text-sm text-ds-accent">{d1?.latest_event_type?.replace(/_/g, " ") ?? "NORMAL"}</div>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-[10px] uppercase">
          <div className="rounded border border-command-border p-2">
            <div className="text-ds-text-tertiary">Agreement</div>
            <div className="mt-1 font-mono text-sm text-ds-text-primary">{mtf.agreement}</div>
          </div>
          <div className="rounded border border-command-border p-2">
            <div className="text-ds-text-tertiary">Propagation</div>
            <div className="mt-1 font-mono text-sm text-ds-text-primary">{mtf.propagation}</div>
          </div>
          <div className="rounded border border-command-border p-2">
            <div className="text-ds-text-tertiary">Divergence</div>
            <div className="mt-1 font-mono text-sm text-ds-text-primary">{mtf.divergence}</div>
          </div>
        </div>
      </div>
    </section>
  );
}

export function MtfHierarchyPanel({ mtf }: { mtf: MtfAlignmentView }) {
  return (
    <section className="rounded border border-command-border bg-command-panel">
      <header className="border-b border-command-border px-4 py-2">
        <h2 className="text-sm font-semibold text-ds-text-primary">MTF Alignment</h2>
        <p className="text-[11px] text-ds-text-tertiary">D1 → H4 → H1 → M30 → M15 · {mtf.alignmentStrength}</p>
      </header>
      <div className="space-y-2 p-3">
        {mtf.hierarchy.map((tf) => {
          const isD1 = tf.timeframe === "D1";
          return (
            <div
              key={tf.timeframe}
              className={`flex items-center gap-3 rounded border px-3 py-2 ${
                isD1 ? "border-command-accent/40 bg-command-accent/5" : "border-command-border/70 bg-command-bg/30"
              }`}
            >
              <span className={`w-10 font-mono font-semibold ${isD1 ? "text-lg text-ds-accent" : "text-xs text-ds-text-tertiary"}`}>
                {tf.timeframe}
              </span>
              <div className="min-w-0 flex-1">
                <div className={`truncate font-mono ${isD1 ? "text-base text-ds-text-primary" : "text-xs text-ds-text-primary"}`}>
                  {tf.latest_event_type?.replace(/_/g, " ") ?? "NORMAL"}
                </div>
                <div className="truncate text-[11px] text-ds-text-tertiary">{tf.auction_state?.replace(/_/g, " ") ?? "—"}</div>
              </div>
              {!isD1 ? <span className="text-[10px] uppercase text-ds-text-tertiary">tactical</span> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}

export function AlertsPanel({ alerts }: { alerts: OperatorAlert[] }) {
  return (
    <section className="rounded border border-command-border bg-command-panel">
      <header className="border-b border-command-border px-4 py-2">
        <h2 className="text-sm font-semibold text-ds-text-primary">Operational Alerts</h2>
        <p className="text-[11px] text-ds-text-tertiary">{alerts.length} active</p>
      </header>
      <div className="max-h-64 space-y-2 overflow-auto p-3">
        {alerts.length === 0 ? (
          <div className="rounded border border-command-green/30 px-3 py-2 text-xs text-ds-status-healthy">No active alerts — system nominal</div>
        ) : (
          alerts.map((alert, index) => (
            <div key={index} className={`rounded border px-3 py-2 text-xs ${ALERT_STYLES[alert.severity]}`}>
              <div className="font-mono font-semibold">{alert.severity}</div>
              <div className="mt-1 text-ds-text-primary">{alert.message}</div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function CompactOntologyPanel({ events }: { events: Record<string, unknown>[] }) {
  const recent = [...events].slice(-5).reverse();
  return (
    <section className="rounded border border-command-border bg-command-panel">
      <header className="border-b border-command-border px-4 py-2">
        <h2 className="text-sm font-semibold text-ds-text-primary">Ontology Activity</h2>
      </header>
      <div className="space-y-1 p-3">
        {recent.length === 0 ? (
          <div className="text-xs text-ds-text-tertiary">No recent dominant events</div>
        ) : (
          recent.map((event, index) => (
            <div key={index} className="rounded border border-command-border/60 px-2 py-1.5 text-xs font-mono">
              {String(event.auction_event_type ?? event.cluster_behavior_resolution ?? "EVENT").replace(/_/g, " ")}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

export function CollapsibleSection({
  title,
  subtitle,
  open,
  onToggle,
  children,
}: {
  title: string;
  subtitle?: string;
  open: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded border border-command-border bg-command-panel/80">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between border-b border-command-border px-4 py-3 text-left hover:bg-command-border/20"
      >
        <div>
          <h2 className="text-sm font-semibold text-ds-text-primary">{title}</h2>
          {subtitle ? <p className="text-[11px] text-ds-text-tertiary">{subtitle}</p> : null}
        </div>
        <span className="text-xs text-ds-text-tertiary">{open ? "▲ Hide" : "▼ Expand"}</span>
      </button>
      {open ? <div className="p-3">{children}</div> : null}
    </section>
  );
}

export function PanelShell({
  title,
  subtitle,
  children,
  className = "",
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col rounded border border-command-border bg-command-panel ${className}`}>
      <header className="border-b border-command-border px-3 py-2">
        <h2 className="text-sm font-semibold tracking-wide text-ds-text-primary">{title}</h2>
        {subtitle ? <p className="text-[11px] text-ds-text-tertiary">{subtitle}</p> : null}
      </header>
      <div className="panel-scroll min-h-0 flex-1 overflow-auto p-3">{children}</div>
    </section>
  );
}

export function MetricCell({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded border border-command-border bg-command-bg/60 p-2">
      <div className="text-[10px] uppercase tracking-wide text-ds-text-tertiary">{label}</div>
      <div className="mt-1 truncate font-mono text-xs text-ds-text-primary">{value === null || value === undefined ? "—" : String(value)}</div>
    </div>
  );
}

export function HealthBadge({ level, label }: { level: HealthLevel | string; label?: string }) {
  const normalized = (level === "SUCCESS" ? "GREEN" : level === "FAILED" ? "RED" : level) as HealthLevel;
  const style = LEVEL_STYLES[normalized] ?? LEVEL_STYLES.YELLOW;
  return (
    <span className={`inline-flex items-center rounded border px-2 py-0.5 text-[10px] font-mono uppercase ${style}`}>
      {label ?? level}
    </span>
  );
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") return Number.isFinite(value) ? value.toFixed(4).replace(/\.?0+$/, "") : "—";
  if (typeof value === "boolean") return value ? "TRUE" : "FALSE";
  if (typeof value === "object") return JSON.stringify(value).slice(0, 80);
  return String(value);
}
