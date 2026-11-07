import { describe, expect, it } from "vitest";
import { mapTradingStateTimeframeSeverity } from "../src/components/ops/tradingStateCardSeverity";

describe("mapTradingStateTimeframeSeverity", () => {
  it("maps OBSERVE to Informational and directional to Healthy", () => {
    expect(mapTradingStateTimeframeSeverity({ trading_state: "OBSERVE" }).label).toBe("Informational");
    expect(mapTradingStateTimeframeSeverity({ trading_state: "LONG_CONTEXT" }).label).toBe("Healthy");
    expect(mapTradingStateTimeframeSeverity({ trading_state: "SHORT_CONTEXT" }).label).toBe("Healthy");
  });

  it("maps stale and unavailable separately", () => {
    expect(mapTradingStateTimeframeSeverity({ trading_state: "LONG_CONTEXT", stale: true }).label).toBe(
      "Warning",
    );
    expect(mapTradingStateTimeframeSeverity({ trading_state: "UNAVAILABLE" }).label).toBe("Critical");
  });
});
