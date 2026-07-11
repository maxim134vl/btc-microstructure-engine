import { useMemo } from "react";
import type { CognitiveDynamicsPoint, CognitiveFeatureMeta } from "../../types/cognitiveReview";
import { asFeatureMeta } from "../../types/cognitiveReview";

const CHART_H = 72;
const STRIP_H = 28;
const PAD = { top: 8, right: 8, bottom: 18, left: 36 };

const PALETTE = ["#38bdf8", "#f472b6", "#a3e635", "#fb923c", "#c084fc", "#2dd4bf", "#facc15", "#fb7185"];

const STATE_COLORS: Record<string, string> = {
  NEUTRAL: "#525252",
  NEUTRAL_VOLUME: "#525252",
  NO_CLIMAX: "#525252",
  BALANCED_RESPONSE: "#94a3b8",
  STRONG_ACCEPTANCE: "#22c55e",
  FAILED_CONTINUATION: "#ef4444",
  AUCTION_STALLED: "#eab308",
  PASSIVE_DEFENSE: "#06b6d4",
  CLIMAX_EXHAUSTION: "#ef4444",
  CLIMAX_CONTINUATION: "#22c55e",
  CLIMAX_ABSORPTION: "#a855f7",
  LOCAL_EXHAUSTION: "#f97316",
  INTERMEDIATE_REVERSAL: "#eab308",
  STRUCTURAL_REVERSAL: "#ef4444",
  IC_CONTINUATION_WEAKENING: "#f97316",
  IC_INITIATIVE_DETERIORATION: "#ef4444",
  IC_ROTATIONAL_PRESSURE: "#eab308",
  M15_ONLY: "#64748b",
  M30_CONFIRMED: "#38bdf8",
  H1_CONFIRMED: "#22c55e",
};

function numericValue(value: unknown): number | null {
  if (value === null || value === undefined) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function stateColor(value: unknown, index: number): string {
  const key = String(value ?? "—");
  return STATE_COLORS[key] ?? PALETTE[index % PALETTE.length];
}

function FeatureLineChart({
  label,
  points,
  beforeBars,
  afterBars,
  color,
}: {
  label: string;
  points: CognitiveDynamicsPoint[];
  beforeBars: number;
  afterBars: number;
  color: string;
}) {
  const width = 320;
  const plotW = width - PAD.left - PAD.right;
  const plotH = CHART_H - PAD.top - PAD.bottom;

  const { path, maxY } = useMemo(() => {
    const numeric = points
      .map((point) => ({ x: point.bar_offset, y: numericValue(point.value) }))
      .filter((point): point is { x: number; y: number } => point.y != null);
    if (numeric.length === 0) {
      return { path: "", maxY: 1 };
    }
    const xs = numeric.map((point) => point.x);
    const ys = numeric.map((point) => point.y);
    const minX = Math.min(...xs, -beforeBars);
    const maxX = Math.max(...xs, afterBars);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const yPad = (maxY - minY) * 0.08 || 0.01;
    const y0 = minY - yPad;
    const y1 = maxY + yPad;

    const toX = (x: number) => PAD.left + ((x - minX) / (maxX - minX || 1)) * plotW;
    const toY = (y: number) => PAD.top + plotH - ((y - y0) / (y1 - y0 || 1)) * plotH;

    const segments: string[] = [];
    let open = false;
    for (const point of numeric.sort((a, b) => a.x - b.x)) {
      const cmd = open ? "L" : "M";
      segments.push(`${cmd}${toX(point.x).toFixed(1)},${toY(point.y).toFixed(1)}`);
      open = true;
    }
    return { path: segments.join(" "), maxY: y1 };
  }, [points, beforeBars, afterBars, plotW, plotH]);

  const eventX = PAD.left + (beforeBars / (beforeBars + afterBars || 1)) * plotW;

  return (
    <div className="rounded border border-neutral-900 bg-neutral-950/60 p-2">
      <div className="mb-1 truncate text-[10px] font-mono text-ds-text-secondary">{label}</div>
      <svg width="100%" viewBox={`0 0 ${width} ${CHART_H}`} className="block">
        <line x1={eventX} x2={eventX} y1={PAD.top} y2={PAD.top + plotH} stroke="#525252" strokeDasharray="3 3" />
        {path ? <path d={path} fill="none" stroke={color} strokeWidth={1.5} /> : null}
        <text x={PAD.left} y={CHART_H - 4} className="fill-neutral-600" fontSize={8}>
          T-{beforeBars}
        </text>
        <text x={width / 2 - 8} y={CHART_H - 4} className="fill-neutral-500" fontSize={8}>
          T=0
        </text>
        <text x={width - PAD.right - 20} y={CHART_H - 4} className="fill-neutral-600" fontSize={8}>
          T+{afterBars}
        </text>
        <text x={4} y={PAD.top + 8} className="fill-neutral-600" fontSize={8}>
          {maxY.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}

function CategoricalStateStrip({
  label,
  points,
  beforeBars,
  afterBars,
}: {
  label: string;
  points: CognitiveDynamicsPoint[];
  beforeBars: number;
  afterBars: number;
}) {
  const width = 320;
  const plotW = width - PAD.left - PAD.right;
  const sorted = [...points].sort((a, b) => a.bar_offset - b.bar_offset);
  const minX = -beforeBars;
  const maxX = afterBars;
  const toX = (x: number) => PAD.left + ((x - minX) / (maxX - minX || 1)) * plotW;
  const barW = Math.max(1, plotW / (maxX - minX + 1));

  const legend = useMemo(() => {
    const seen = new Map<string, number>();
    for (const point of sorted) {
      const key = displayState(point.value);
      if (!seen.has(key)) seen.set(key, seen.size);
    }
    return [...seen.entries()];
  }, [sorted]);

  const eventX = PAD.left + (beforeBars / (beforeBars + afterBars || 1)) * plotW;

  return (
    <div className="rounded border border-neutral-900 bg-neutral-950/60 p-2">
      <div className="mb-1 truncate text-[10px] font-mono text-ds-text-secondary">{label}</div>
      <svg width="100%" viewBox={`0 0 ${width} ${STRIP_H + 14}`} className="block">
        <line x1={eventX} x2={eventX} y1={4} y2={STRIP_H} stroke="#525252" strokeDasharray="3 3" />
        {sorted.map((point) => {
          const key = displayState(point.value);
          const colorIdx = legend.find(([labelKey]) => labelKey === key)?.[1] ?? 0;
          return (
            <rect
              key={`${point.bar_offset}-${key}`}
              x={toX(point.bar_offset) - barW / 2}
              y={6}
              width={barW}
              height={STRIP_H - 8}
              fill={stateColor(key, colorIdx)}
              opacity={0.85}
            />
          );
        })}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5">
        {legend.map(([key, idx]) => (
          <span key={key} className="text-[9px] font-mono" style={{ color: stateColor(key, idx) }}>
            {key}
          </span>
        ))}
      </div>
    </div>
  );
}

function displayState(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

export function CognitiveDynamicsChart({
  series,
  selectedFeatures,
  featureMeta: featureMetaInput,
  beforeBars,
  afterBars,
}: {
  series: Record<string, CognitiveDynamicsPoint[]>;
  selectedFeatures: string[];
  featureMeta?: CognitiveFeatureMeta[];
  beforeBars: number;
  afterBars: number;
}) {
  const featureMeta = asFeatureMeta(featureMetaInput);

  const dtypeByName = useMemo(() => {
    const map = new Map<string, CognitiveFeatureMeta["dtype"]>();
    for (const item of featureMeta) map.set(item.name, item.dtype);
    return map;
  }, [featureMeta]);

  const labelByName = useMemo(() => {
    const map = new Map<string, string>();
    for (const item of featureMeta) map.set(item.name, item.label);
    return map;
  }, [featureMeta]);

  if (selectedFeatures.length === 0) {
    return <div className="text-[11px] text-ds-text-tertiary">Select features to plot dynamics.</div>;
  }

  return (
    <div className="space-y-2">
      {selectedFeatures.map((name, index) => {
        const label = labelByName.get(name) ?? name;
        const points = series[name] ?? [];
        const dtype = dtypeByName.get(name) ?? "numeric";
        if (dtype === "categorical") {
          return (
            <CategoricalStateStrip
              key={name}
              label={label}
              points={points}
              beforeBars={beforeBars}
              afterBars={afterBars}
            />
          );
        }
        return (
          <FeatureLineChart
            key={name}
            label={label}
            points={points}
            beforeBars={beforeBars}
            afterBars={afterBars}
            color={PALETTE[index % PALETTE.length]}
          />
        );
      })}
    </div>
  );
}

export function CognitiveCompareChart({
  groups,
  featureName,
  featureLabel,
  beforeBars,
  afterBars,
}: {
  groups: Array<{ label: string; trajectories: Record<string, { bar_offset: number; mean: number }[]> }>;
  featureName: string;
  featureLabel: string;
  beforeBars: number;
  afterBars: number;
}) {
  const width = 360;
  const height = 120;
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  const paths = useMemo(() => {
    const allPoints = groups.flatMap((group) => group.trajectories[featureName] ?? []);
    if (allPoints.length === 0) return [];
    const minX = -beforeBars;
    const maxX = afterBars;
    const ys = allPoints.map((point) => point.mean);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const yPad = (maxY - minY) * 0.08 || 0.01;
    const y0 = minY - yPad;
    const y1 = maxY + yPad;
    const toX = (x: number) => PAD.left + ((x - minX) / (maxX - minX || 1)) * plotW;
    const toY = (y: number) => PAD.top + plotH - ((y - y0) / (y1 - y0 || 1)) * plotH;

    return groups.map((group, index) => {
      const points = (group.trajectories[featureName] ?? []).sort((a, b) => a.bar_offset - b.bar_offset);
      const segments = points.map((point, i) => {
        const cmd = i === 0 ? "M" : "L";
        return `${cmd}${toX(point.bar_offset).toFixed(1)},${toY(point.mean).toFixed(1)}`;
      });
      return { label: group.label, path: segments.join(" "), color: PALETTE[index % PALETTE.length] };
    });
  }, [groups, featureName, beforeBars, afterBars, plotW, plotH]);

  if (paths.length === 0) {
    return null;
  }

  const eventX = PAD.left + (beforeBars / (beforeBars + afterBars || 1)) * plotW;

  return (
    <div className="rounded border border-neutral-900 bg-neutral-950/60 p-2">
      <div className="mb-1 text-[10px] font-mono text-ds-text-secondary">{featureLabel}</div>
      <svg width="100%" viewBox={`0 0 ${width} ${height}`} className="block">
        <line x1={eventX} x2={eventX} y1={PAD.top} y2={PAD.top + plotH} stroke="#525252" strokeDasharray="3 3" />
        {paths.map((item) =>
          item.path ? (
            <path key={item.label} d={item.path} fill="none" stroke={item.color} strokeWidth={1.5} />
          ) : null,
        )}
      </svg>
      <div className="mt-1 flex flex-wrap gap-2">
        {paths.map((item) => (
          <span key={item.label} className="text-[9px] font-mono" style={{ color: item.color }}>
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}
