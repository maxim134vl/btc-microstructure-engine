import type { MarketStateQuery, MarketStateSnapshot } from "../types/marketState";

const API = "/api";

export async function fetchMarketStateSnapshot(query: MarketStateQuery = {}): Promise<MarketStateSnapshot> {
  const params = new URLSearchParams();
  params.set("timeframe", query.timeframe ?? "M15");
  params.set("limit", String(query.limit ?? 500));
  params.set("mode", query.mode ?? "latest");
  if (query.range) params.set("range", query.range);
  if (query.from) params.set("from", query.from);
  if (query.to) params.set("to", query.to);

  const response = await fetch(`${API}/market-state?${params.toString()}`);
  if (!response.ok) throw new Error(`market state snapshot ${response.status}`);
  return response.json();
}
