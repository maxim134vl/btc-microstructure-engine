import type { ReviewCandleBar } from "../../types/eventReview";

export type ReactionSignificance =
  | "Шум"
  | "Слабая реакция"
  | "Заметная реакция"
  | "Сильная реакция"
  | "Очень сильная реакция"
  | "Экстремальная реакция";

export interface MeasurementPreview {
  start_index: number;
  end_index: number;
  start_timestamp: string;
  end_timestamp: string;
  start_price: number;
  end_price: number;
  return_pct: number;
  absolute_price_change: number;
  bars_count: number;
  max_favorable_excursion: number;
  max_adverse_excursion: number;
  reaction_significance: ReactionSignificance;
}

export function classifyReactionSignificance(returnPct: number): ReactionSignificance {
  const magnitude = Math.abs(returnPct);
  if (magnitude < 0.5) return "Шум";
  if (magnitude < 1.0) return "Слабая реакция";
  if (magnitude < 1.5) return "Заметная реакция";
  if (magnitude < 2.0) return "Сильная реакция";
  if (magnitude < 3.0) return "Очень сильная реакция";
  return "Экстремальная реакция";
}

export function computeMeasurement(
  bars: ReviewCandleBar[],
  startIndex: number,
  endIndex: number,
): MeasurementPreview {
  const i = Math.max(0, Math.min(startIndex, endIndex));
  const j = Math.min(bars.length - 1, Math.max(startIndex, endIndex));
  const startBar = bars[i];
  const endBar = bars[j];
  if (!startBar || !endBar) {
    throw new Error("Invalid bar indices");
  }

  const startPrice = startBar.close;
  const endPrice = endBar.close;
  const returnPct = ((endPrice - startPrice) / startPrice) * 100;
  const absoluteChange = endPrice - startPrice;

  let maxUpPct = 0;
  let maxDownPct = 0;
  for (let k = i; k <= j; k++) {
    const bar = bars[k];
    if (!bar) continue;
    maxUpPct = Math.max(maxUpPct, ((bar.high - startPrice) / startPrice) * 100);
    maxDownPct = Math.max(maxDownPct, ((startPrice - bar.low) / startPrice) * 100);
  }

  const mfe = endPrice >= startPrice ? maxUpPct : maxDownPct;
  const mae = endPrice >= startPrice ? maxDownPct : maxUpPct;

  return {
    start_index: i,
    end_index: j,
    start_timestamp: startBar.timestamp,
    end_timestamp: endBar.timestamp,
    start_price: startPrice,
    end_price: endPrice,
    return_pct: returnPct,
    absolute_price_change: absoluteChange,
    bars_count: j - i + 1,
    max_favorable_excursion: mfe,
    max_adverse_excursion: mae,
    reaction_significance: classifyReactionSignificance(returnPct),
  };
}

export function formatReturnPct(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatUsdChange(value: number): string {
  const sign = value >= 0 ? "+" : "";
  return `${sign}${Math.round(value).toLocaleString("en-US")} USD`;
}

export function reactionToMeasurement(
  bars: ReviewCandleBar[],
  reaction: {
    start_timestamp: string;
    end_timestamp: string;
    start_price: number;
    end_price: number;
    return_pct: number;
    absolute_price_change: number;
    bars_count: number;
    max_favorable_excursion: number;
    max_adverse_excursion: number;
    reaction_significance: string;
  },
): MeasurementPreview | null {
  const startIndex = bars.findIndex((bar) => bar.timestamp === reaction.start_timestamp);
  const endIndex = bars.findIndex((bar) => bar.timestamp === reaction.end_timestamp);
  if (startIndex < 0 || endIndex < 0) return null;
  return {
    start_index: startIndex,
    end_index: endIndex,
    start_timestamp: reaction.start_timestamp,
    end_timestamp: reaction.end_timestamp,
    start_price: reaction.start_price,
    end_price: reaction.end_price,
    return_pct: reaction.return_pct,
    absolute_price_change: reaction.absolute_price_change,
    bars_count: reaction.bars_count,
    max_favorable_excursion: reaction.max_favorable_excursion,
    max_adverse_excursion: reaction.max_adverse_excursion,
    reaction_significance: reaction.reaction_significance as ReactionSignificance,
  };
}
