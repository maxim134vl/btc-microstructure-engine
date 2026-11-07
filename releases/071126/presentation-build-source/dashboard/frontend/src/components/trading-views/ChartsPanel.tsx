import type { ReactNode } from "react";
import { useTranslation } from "../../i18n";
import { pnlTone, pct, signedPct, signedUsd } from "./format";
import {
  type DayResult,
  type EquityPoint,
} from "./ledger";
import { useTradeJournal } from "./useTradeJournal";
import { ViewFrame } from "./ViewFrame";

function MetricCard({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <article className="ops-card px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-[0.06em] text-ds-text-tertiary">{label}</p>
      <p className="mt-1 font-ds-display text-[22px] font-semibold tabular-nums" style={tone ? { color: tone } : undefined}>
        {value}
      </p>
      {hint ? <p className="mt-1 text-[11px] text-ds-text-tertiary">{hint}</p> : null}
    </article>
  );
}

function linePath(
  values: number[],
  width: number,
  height: number,
  pad = 16,
  includeZero = false,
): { line: string; area: string; zeroY: number | null } {
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (includeZero) {
    yMin = Math.min(yMin, 0);
    yMax = Math.max(yMax, 0);
  }
  if (yMin === yMax) {
    yMin -= 1;
    yMax += 1;
  }
  const x = (i: number) => pad + (values.length <= 1 ? innerW / 2 : (i / (values.length - 1)) * innerW);
  const y = (v: number) => pad + ((yMax - v) / (yMax - yMin)) * innerH;
  const coords = values.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`);
  const line = coords.length ? `M ${coords.join(" L ")}` : "";
  const baseline = includeZero ? y(0) : pad + innerH;
  const area = coords.length
    ? `M ${x(0).toFixed(2)},${baseline.toFixed(2)} L ${coords.join(" L ")} L ${x(values.length - 1).toFixed(2)},${baseline.toFixed(2)} Z`
    : "";
  const zeroY = includeZero || (yMin <= 0 && yMax >= 0) ? y(0) : null;
  return { line, area, zeroY };
}

type RingSlice = {
  key: string;
  label: string;
  value: number;
  color: string;
};

function Donut({ slices }: { slices: RingSlice[] }) {
  const { t } = useTranslation();
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  const active = slices.filter((slice) => slice.value > 0);
  const gap = active.length > 1 ? 3 : 0;
  let cursor = 0;

  return (
    <div className="flex items-center gap-4 px-3.5 py-4 sm:gap-6 sm:px-5">
      <div className="relative h-[148px] w-[148px] shrink-0">
        <svg viewBox="0 0 120 120" className="h-full w-full" role="img">
          <circle cx="60" cy="60" r={radius} fill="none" stroke="var(--ds-color-border)" strokeWidth="12" />
          {active.map((slice) => {
            const span = total ? (slice.value / total) * circumference : 0;
            const length = Math.max(span - gap, 0);
            const dashOffset = -cursor;
            cursor += span;
            return (
              <circle
                key={slice.key}
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke={slice.color}
                strokeWidth="12"
                strokeDasharray={`${length} ${circumference - length}`}
                strokeDashoffset={dashOffset}
                transform="rotate(-90 60 60)"
              />
            );
          })}
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-ds-display text-[22px] font-semibold tabular-nums text-ds-text-primary">{total}</span>
          <span className="text-[10px] font-medium uppercase tracking-[0.06em] text-ds-text-tertiary">
            {t("tradingViews.statement.trades")}
          </span>
        </div>
      </div>
      <ul className="min-w-0 flex-1 space-y-2">
        {slices.map((slice) => {
          const share = total ? (slice.value / total) * 100 : 0;
          return (
            <li key={slice.key} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="flex min-w-0 items-center gap-2 text-ds-text-primary">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: slice.color }} />
                <span className="truncate">{slice.label}</span>
              </span>
              <span className="shrink-0 font-medium tabular-nums text-ds-text-secondary">
                {slice.value}
                <span className="ml-1.5 text-ds-text-tertiary">{pct(share)}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function ChartCard({
  title,
  hint,
  children,
}: {
  title: string;
  hint: string;
  children: ReactNode;
}) {
  return (
    <article className="ops-card overflow-hidden">
      <header className="border-b border-ds-border/35 px-3.5 py-3">
        <h3 className="text-[14px] font-semibold text-ds-text-primary">{title}</h3>
        <p className="mt-0.5 text-[11px] text-ds-text-tertiary">{hint}</p>
      </header>
      {children}
    </article>
  );
}

function EmptyChart({ label }: { label: string }) {
  return <p className="px-3.5 py-8 text-[13px] text-ds-text-secondary">{label}</p>;
}

function EquityChart({ points }: { points: EquityPoint[] }) {
  const width = 720;
  const height = 220;
  if (!points.length) return null;
  const values = points.map((point) => point.equityUsd);
  const path = linePath(values, width, height, 16, false);
  const last = points[points.length - 1];
  const up = (last?.pnlUsd ?? 0) >= 0;
  const stroke = up ? "var(--ds-status-healthy)" : "var(--ds-status-error)";
  const fill = up
    ? "color-mix(in srgb, var(--ds-status-healthy) 16%, transparent)"
    : "color-mix(in srgb, var(--ds-status-error) 16%, transparent)";
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-[220px] w-full" role="img">
      {path.zeroY != null ? null : null}
      <path d={path.area} fill={fill} />
      <path d={path.line} fill="none" stroke={stroke} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function CumulativeChart({ points }: { points: EquityPoint[] }) {
  const width = 720;
  const height = 200;
  if (!points.length) return null;
  const values = points.map((point) => point.pnlUsd);
  const path = linePath(values, width, height, 16, true);
  const last = values[values.length - 1] ?? 0;
  const stroke = last >= 0 ? "var(--ds-status-healthy)" : "var(--ds-status-error)";
  const fill =
    last >= 0
      ? "color-mix(in srgb, var(--ds-status-healthy) 16%, transparent)"
      : "color-mix(in srgb, var(--ds-status-error) 16%, transparent)";
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-[200px] w-full" role="img">
      {path.zeroY != null ? (
        <line
          x1="16"
          x2={width - 16}
          y1={path.zeroY}
          y2={path.zeroY}
          stroke="currentColor"
          strokeOpacity="0.22"
          strokeDasharray="4 4"
          className="text-ds-text-tertiary"
        />
      ) : null}
      <path d={path.area} fill={fill} />
      <path d={path.line} fill="none" stroke={stroke} strokeWidth="2.25" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

function DailyPnlChart({ days }: { days: DayResult[] }) {
  const width = 720;
  const height = 200;
  const pad = 16;
  if (!days.length) return null;
  const values = days.map((day) => day.pnlUsd);
  const max = Math.max(...values.map((value) => Math.abs(value)), 1);
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const zeroY = pad + innerH / 2;
  const gap = 8;
  const barW = days.length ? (innerW - gap * (days.length - 1)) / days.length : 0;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-[200px] w-full" role="img">
      <line
        x1={pad}
        x2={width - pad}
        y1={zeroY}
        y2={zeroY}
        stroke="currentColor"
        strokeOpacity="0.22"
        className="text-ds-text-tertiary"
      />
      {days.map((day, index) => {
        const h = (Math.abs(day.pnlUsd) / max) * (innerH / 2);
        const x = pad + index * (barW + gap);
        const y = day.pnlUsd >= 0 ? zeroY - h : zeroY;
        return (
          <rect
            key={day.date}
            x={x}
            y={y}
            width={Math.max(barW, 1)}
            height={Math.max(h, 1)}
            rx="3"
            fill={day.pnlUsd >= 0 ? "var(--ds-status-healthy)" : "var(--ds-status-error)"}
            opacity="0.9"
          >
            <title>{`${day.date} ${signedUsd(day.pnlUsd)}`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

function WinRateChart({ days }: { days: DayResult[] }) {
  const width = 720;
  const height = 180;
  if (!days.length) return null;
  const values = days.map((day) => day.winRate * 100);
  const path = linePath(values, width, height, 16, true);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block h-[180px] w-full" role="img">
      <path
        d={path.line}
        fill="none"
        stroke="var(--ds-color-accent, #007aff)"
        strokeWidth="2.25"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ChartsPanel({ fillWindow = false }: { fillWindow?: boolean }) {
  const { t } = useTranslation();
  const journal = useTradeJournal();
  const equity = journal.equityCurve;
  const days: DayResult[] = []; // Requires an existing native daily-result publication.
  const summary = { ...journal.ownerSummary, returnPct: null as number | null, maxDrawdownPct: null as number | null, profitFactor: null as number | null };
  const empty = t("tradingViews.unavailable");
  const sideSlices: RingSlice[] = []; // No client-side side/exit count reconstruction.
  const exitSlices: RingSlice[] = [];

  return (
    <ViewFrame fillWindow={fillWindow}>
      {journal.connected ? null : (
        <p className="px-0.5 text-[12px] text-ds-text-secondary">{t("tradingViews.unavailable")}</p>
      )}
      <section className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4" data-section="charts-summary">
        <MetricCard
          label={t("tradingViews.charts.netPnl")}
          value={signedUsd(summary.netPnlUsd)}
          hint={summary.returnPct == null ? "—" : signedPct(summary.returnPct)}
          tone={pnlTone(summary.netPnlUsd)}
        />
        <MetricCard label={t("tradingViews.charts.winRate")} value="—" hint="Owner metric unavailable" />
        <MetricCard
          label={t("tradingViews.charts.maxDrawdown")}
          value={summary.maxDrawdownPct == null ? "—" : pct(summary.maxDrawdownPct)}
          tone="var(--ds-status-error)"
        />
        <MetricCard
          label={t("tradingViews.charts.profitFactor")}
          value={summary.profitFactor == null ? "—" : summary.profitFactor.toFixed(2)}
        />
      </section>
      <section className="grid gap-3.5 xl:grid-cols-2" data-section="charts-mix">
        <ChartCard title={t("tradingViews.charts.sideMix")} hint={t("tradingViews.charts.sideMixHint")}>
          {sideSlices.length ? <Donut slices={sideSlices} /> : <EmptyChart label={empty} />}
        </ChartCard>
        <ChartCard title={t("tradingViews.charts.exits")} hint={t("tradingViews.charts.exitsHint")}>
          {exitSlices.length ? <Donut slices={exitSlices} /> : <EmptyChart label={empty} />}
        </ChartCard>
      </section>
      <section className="grid gap-3.5 xl:grid-cols-2" data-section="charts-primary">
        <ChartCard title={t("tradingViews.charts.equity")} hint={t("tradingViews.charts.equityHint")}>
          {equity.length ? <EquityChart points={equity} /> : <EmptyChart label={empty} />}
        </ChartCard>
        <ChartCard title={t("tradingViews.charts.cumulative")} hint={t("tradingViews.charts.cumulativeHint")}>
          {equity.length ? <CumulativeChart points={equity} /> : <EmptyChart label={empty} />}
        </ChartCard>
        <ChartCard title={t("tradingViews.charts.dailyPnl")} hint={t("tradingViews.charts.dailyPnlHint")}>
          {days.length ? <DailyPnlChart days={days} /> : <EmptyChart label={empty} />}
        </ChartCard>
        <ChartCard title={t("tradingViews.charts.winRateSeries")} hint={t("tradingViews.charts.winRateHint")}>
          {days.length ? <WinRateChart days={days} /> : <EmptyChart label={empty} />}
        </ChartCard>
      </section>
    </ViewFrame>
  );
}
