import type { ChartAnnotation, CognitionBar, MajorVolumeMarker, VolumeClassLabel } from "../../types/visualCognition";
import { EVENT_MARKER_COLORS } from "./IntraCandleMarker";

/** Reference: Auction Internal Execution Map */
export const CHART = {
  width: 720,
  priceHeight: 160,
  volumeHeight: 52,
  pad: { top: 10, right: 12, bottom: 22, left: 56 },
  volumeGap: 4,
  minBarWidth: 1.75,
  maxBarWidth: 4,
  scrollHeight: 360,
};

export function barWidthForCount(count: number): number {
  const { minBarWidth, maxBarWidth } = CHART;
  if (count <= 800) return maxBarWidth;
  if (count <= 2000) return 2.5;
  if (count <= 5000) return 2;
  return minBarWidth;
}

export const EXECUTION_MAP = {
  background: "#000000",
  grid: "#333333",
  axis: "#888888",
  neutralStroke: "#b0b8c4",
  neutralFill: "#000000",
};

/** Apple Stocks–style chart palette for research views */
export const APPLE_EXECUTION_MAP = {
  background: "#0f1115",
  grid: "rgba(255,255,255,0.06)",
  axis: "rgba(152,152,157,0.85)",
  neutralStroke: "rgba(210,210,215,0.72)",
  neutralFill: "rgba(255,255,255,0.04)",
};

const VOLUME_CLASS_COLORS: Record<VolumeClassLabel, string> = EVENT_MARKER_COLORS;

const MARKER_COLORS: Record<MajorVolumeMarker, string> = {
  BUYING_CLIMAX: "#22c55e",
  SELLING_CLIMAX: "#ef4444",
  STOPPING_VOLUME: "#eab308",
};

export function formatPrice(value: number): string {
  if (value >= 10000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  if (value >= 100) return value.toFixed(1);
  return value.toFixed(2);
}

export function formatVolume(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}K`;
  return value.toFixed(0);
}

export function formatTime(timestamp: string): string {
  const d = new Date(timestamp);
  if (Number.isNaN(d.getTime())) return timestamp.slice(5, 16);
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hour = String(d.getUTCHours()).padStart(2, "0");
  const minute = String(d.getUTCMinutes()).padStart(2, "0");
  return `${month}-${day} ${hour}:${minute}`;
}

export function priceTicks(minP: number, maxP: number, count = 5): number[] {
  const span = maxP - minP || 1;
  const step = span / Math.max(count - 1, 1);
  return Array.from({ length: count }, (_, i) => minP + step * i);
}

export function timeTickIndices(barCount: number, maxTicks = 5): number[] {
  if (barCount <= 1) return [0];
  const step = Math.max(1, Math.floor((barCount - 1) / (maxTicks - 1)));
  const indices: number[] = [];
  for (let i = 0; i < barCount; i += step) indices.push(i);
  if (indices[indices.length - 1] !== barCount - 1) indices.push(barCount - 1);
  return indices;
}

export function primaryStage1Event(bar: CognitionBar): VolumeClassLabel | null {
  const label = bar.volume_location_markers?.[0]?.event ?? bar.volume_class_label;
  if (!label || label === "NORMAL" || label === "LOW_SMALL") return null;
  return label;
}

export function volumeClassColor(bar: CognitionBar): string {
  if (bar.volume_bar_color) return bar.volume_bar_color;
  const label = bar.volume_class_label ?? "NORMAL";
  return VOLUME_CLASS_COLORS[label] ?? VOLUME_CLASS_COLORS.NORMAL;
}

export function colorForVolumeClass(label: VolumeClassLabel): string {
  return VOLUME_CLASS_COLORS[label] ?? VOLUME_CLASS_COLORS.NORMAL;
}

export function markerColor(event: MajorVolumeMarker): string {
  return MARKER_COLORS[event];
}

export function volumeClassShortLabel(label: VolumeClassLabel): string | null {
  switch (label) {
    case "BUYING_CLIMAX":
      return "BC";
    case "SELLING_CLIMAX":
      return "SC";
    case "STOPPING_VOLUME":
      return "SV";
    case "HIGH_VARIANCE_VOLUME":
      return "HAV";
    case "ABSORPTION":
      return "ABS";
    default:
      return null;
  }
}

export function truncateAnnotation(text: string, max = 28): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

export type PlotScales = {
  xFor: (index: number) => number;
  yFor: (price: number) => number;
  barW: number;
  plotW: number;
  plotH: number;
  pad: typeof CHART.pad;
};

export function buildScales(
  bars: CognitionBar[],
  plotH: number,
  chartWidth = CHART.width,
): PlotScales & { minP: number; maxP: number } {
  const { pad } = CHART;
  const plotW = chartWidth - pad.left - pad.right;
  const minP = Math.min(...bars.map((b) => b.low));
  const maxP = Math.max(...bars.map((b) => b.high));
  const span = maxP - minP || 1;
  const barW = Math.max(3, plotW / bars.length - 1.5);

  return {
    minP,
    maxP,
    pad,
    plotW,
    plotH,
    barW,
    xFor: (index: number) => pad.left + (index / Math.max(bars.length - 1, 1)) * plotW,
    yFor: (price: number) => pad.top + plotH - ((price - minP) / span) * plotH,
  };
}

export function buildVolumeScales(bars: CognitionBar[], top: number, plotH: number): {
  maxV: number;
  yFor: (volume: number) => number;
  top: number;
  plotH: number;
} {
  const maxV = Math.max(...bars.map((b) => b.volume ?? 0), 1);
  return {
    maxV,
    top,
    plotH,
    yFor: (volume: number) => top + plotH - (volume / maxV) * plotH,
  };
}

export function priceFractionInBar(high: number, low: number, price: number): number {
  const span = high - low || 1;
  return Math.max(0, Math.min(1, (price - low) / span));
}

export function annotationY(
  annotation: ChartAnnotation,
  bars: CognitionBar[],
  yFor: (price: number) => number,
  padTop: number,
): number {
  const bar = bars[annotation.bar_index];
  if (!bar) return padTop + 4;
  return yFor(bar.high) - 10;
}

export function totalChartHeight(): number {
  const { priceHeight, volumeHeight, pad, volumeGap } = CHART;
  return priceHeight + volumeGap + volumeHeight + pad.bottom;
}

/** Default visible bar count per timeframe — TradingView-style initial viewport. */
export function defaultVisibleBarsForTimeframe(timeframe: string): number {
  switch (timeframe.toUpperCase()) {
    case "M15":
      return 200;
    case "H1":
      return 150;
    case "H4":
      return 115;
    case "D1":
      return 75;
    default:
      return 150;
  }
}

/** Derive plot regions from container size (analysis layout — fills available space). */
export function layoutFromSize(containerWidth: number, containerHeight: number) {
  const { pad, volumeGap } = CHART;
  const volumeHeight = Math.max(52, Math.round(containerHeight * 0.13));
  const pricePlotH = Math.max(180, containerHeight - volumeHeight - volumeGap - pad.bottom);
  const volumeTop = pad.top + pricePlotH + volumeGap;
  const volumePlotH = volumeHeight - 6;
  const height = volumeTop + volumePlotH + pad.bottom;

  return {
    width: containerWidth,
    height,
    pricePlotH,
    volumeHeight,
    volumeTop,
    volumePlotH,
    pad,
    volumeGap,
  };
}
