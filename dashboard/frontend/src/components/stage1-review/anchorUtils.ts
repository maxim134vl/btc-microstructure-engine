import type { ManualAnchor } from "../../types/manualAnnotations";
import type { ReviewCandleBar } from "../../types/eventReview";

export interface AnchorGeometry {
  anchorId: string;
  anchorType: "single" | "range";
  startIndex: number;
  endIndex: number;
  startPrice: number;
  endPrice: number;
  midIndex: number;
  midPrice: number;
  label: string;
  isRange: boolean;
}

export const ANCHOR_LABEL_COLORS: Record<string, string> = {
  "Источник объема": "#f59e0b",
  Поглощение: "#a855f7",
  Накопление: "#22c55e",
  Распределение: "#ef4444",
  "Зона реакции": "#38bdf8",
  Тест: "#eab308",
  "Кульминация покупок": "#4ade80",
  "Кульминация продаж": "#f87171",
  "Останавливающий объем": "#c084fc",
  Другое: "#94a3b8",
};

export function anchorColor(label: string): string {
  return ANCHOR_LABEL_COLORS[label] ?? "#94a3b8";
}

function indexForTimestamp(bars: ReviewCandleBar[], timestamp: string): number {
  return bars.findIndex((bar) => bar.timestamp === timestamp);
}

export function resolveAnchorGeometry(
  anchor: ManualAnchor,
  bars: ReviewCandleBar[],
): AnchorGeometry | null {
  const startIndex = indexForTimestamp(bars, anchor.start_timestamp);
  const endIndex = indexForTimestamp(bars, anchor.end_timestamp);
  if (startIndex < 0 || endIndex < 0) return null;

  const i = Math.min(startIndex, endIndex);
  const j = Math.max(startIndex, endIndex);
  const isRange = anchor.anchor_type === "range" && i !== j;
  const midIndex = (i + j) / 2;
  const midPrice = (anchor.start_price + anchor.end_price) / 2;

  return {
    anchorId: anchor.anchor_id,
    anchorType: anchor.anchor_type,
    startIndex: i,
    endIndex: j,
    startPrice: anchor.start_price,
    endPrice: anchor.end_price,
    midIndex,
    midPrice,
    label: anchor.anchor_label_ru,
    isRange,
  };
}

export function resolveAllAnchorGeometries(
  anchors: ManualAnchor[],
  bars: ReviewCandleBar[],
): AnchorGeometry[] {
  return anchors
    .map((anchor) => resolveAnchorGeometry(anchor, bars))
    .filter((item): item is AnchorGeometry => item != null);
}

export function formatAnchorRange(anchor: ManualAnchor): string {
  if (anchor.anchor_type === "single" || anchor.start_timestamp === anchor.end_timestamp) {
    return anchor.start_timestamp;
  }
  return `${anchor.start_timestamp} → ${anchor.end_timestamp}`;
}
