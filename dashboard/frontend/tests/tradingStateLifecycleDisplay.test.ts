import { describe, expect, it } from "vitest";
import {
  displayActiveContext,
  displayLifecycleState,
  displayProvisionalContext,
} from "../src/components/ops/tradingStateLifecycleDisplay";

describe("OPS1.8 provisional vs active display", () => {
  it("keeps CHALLENGED when provisional OBSERVE and active LONG", () => {
    const row = {
      provisional_market_context: "OBSERVE",
      active_market_context: "LONG_CONTEXT",
      lifecycle_state: "CHALLENGED",
    };
    expect(displayProvisionalContext(row)).toBe("OBSERVE");
    expect(displayActiveContext(row)).toBe("LONG_CONTEXT");
    expect(displayLifecycleState(row)).toBe("CHALLENGED");
  });

  it("shows NO_ACTIVE_CONTEXT when active is null", () => {
    const row = {
      provisional_market_context: "OBSERVE",
      active_market_context: null,
      lifecycle_state: "CHALLENGED",
    };
    expect(displayLifecycleState(row)).toBe("NO_ACTIVE_CONTEXT");
    expect(displayActiveContext(row)).toBe("—");
  });
});
