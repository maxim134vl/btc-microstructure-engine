"""Analyze continuation failure after climax events."""

from __future__ import annotations

from scripts.replay_validation.ontology.replay_utils import run_climax


def run(limit: int = 10) -> None:
    events = run_climax()
    if len(events) == 0 or "auction_event_type" not in events.columns:
        print("CONTINUATION FAILURE ANALYSIS")
        print("=" * 60)
        print("No climax events detected")
        return

    tracked = events[
        events["auction_event_type"].isin(["STOPPING_VOLUME", "SELLING_CLIMAX"])
    ].tail(limit)

    print("CONTINUATION FAILURE ANALYSIS")
    print("=" * 60)
    if len(tracked) == 0:
        print("No tracked sell-side events")
        return

    for _, row in tracked.iterrows():
        print(
            f"{row.get('timestamp')} {row.get('auction_event_type')} "
            f"continuation_failure={row.get('continuation_failure_rate', 0):.3f} "
            f"inventory_transfer={row.get('inventory_transfer_quality', 0):.3f}"
        )

    mean_failure = tracked["continuation_failure_rate"].mean()
    print(f"\nMean continuation failure rate: {mean_failure:.3f}")


if __name__ == "__main__":
    run()
