import { describe, expect, it } from "vitest";
import { displayLifecycleState } from "../src/components/ops/tradingStateLifecycleDisplay";

describe("OPS1.7 trading state lifecycle display", () => {
  it("does not show CHALLENGED for OBSERVE with null episode/event", () => {
    expect(
      displayLifecycleState({
        trading_state: "OBSERVE",
        lifecycle_state: "CHALLENGED",
        lifecycle_episode_id: null,
        context_event_id: null,
      }),
    ).toBe("NO_ACTIVE_CONTEXT");
  });

  it("keeps CHALLENGED when directional episode/event exist", () => {
    expect(
      displayLifecycleState({
        trading_state: "LONG_CONTEXT",
        lifecycle_state: "CHALLENGED",
        lifecycle_episode_id: "H4:prov:1",
        context_event_id: "CTX_d25",
      }),
    ).toBe("CHALLENGED");
  });
});
