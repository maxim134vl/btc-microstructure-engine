"""Replay post-event entropy / efficiency decay evolution."""

from __future__ import annotations

from scripts.replay_validation.ontology.replay_utils import run_climax


def run(limit: int = 10) -> None:
    events = run_climax()
    if len(events) == 0 or "auction_event_type" not in events.columns:
        print("POST-EVENT ENTROPY DECAY REPLAY")
        print("=" * 60)
        print("No climax events detected")
        return

    tracked = events[
        events["auction_event_type"].isin(["STOPPING_VOLUME", "SELLING_CLIMAX"])
    ].tail(limit)

    print("POST-EVENT ENTROPY DECAY REPLAY")
    print("=" * 60)
    if len(tracked) == 0:
        print("No tracked sell-side events")
        return

    for _, row in tracked.iterrows():
        print(
            f"{row.get('timestamp')} {row.get('auction_event_type')} "
            f"entropy_shift={row.get('post_climax_entropy_shift', 0):.3f} "
            f"stabilization={row.get('stabilization_duration', 0):.1f}"
        )


if __name__ == "__main__":
    run()
