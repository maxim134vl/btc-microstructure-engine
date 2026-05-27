"""Compare absorption vs capitulation semantic separation."""

from __future__ import annotations

from scripts.replay_validation.ontology.replay_utils import run_climax


def run() -> None:
    events = run_climax()
    print("ABSORPTION VS CAPITULATION REPLAY")
    print("=" * 60)
    if len(events) == 0 or "auction_event_type" not in events.columns:
        print("No climax events detected")
        return

    stopping = events[events["auction_event_type"] == "STOPPING_VOLUME"]
    selling = events[events["auction_event_type"] == "SELLING_CLIMAX"]
    overlap = events[
        events["auction_event_type"].isin(["STOPPING_VOLUME", "SELLING_CLIMAX"])
    ]

    print(f"STOPPING_VOLUME events: {len(stopping)}")
    print(f"SELLING_CLIMAX events: {len(selling)}")
    print(f"Combined sell-side events: {len(overlap)}")

    if len(stopping) > 0:
        print(
            f"  stopping mean decay={stopping['efficiency_decay'].mean():.3f} "
            f"mean close_position={stopping['close_position_ratio'].mean():.3f}"
        )
    if len(selling) > 0:
        print(
            f"  selling mean decay={selling['efficiency_decay'].mean():.3f} "
            f"mean close_position={selling['close_position_ratio'].mean():.3f}"
        )

    dual_labels = stopping.index.intersection(selling.index)
    print(f"Overlap collapse count: {len(dual_labels)}")


if __name__ == "__main__":
    run()
