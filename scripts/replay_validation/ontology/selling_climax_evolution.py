"""Replay SELLING_CLIMAX post-event behavioral evolution."""

from __future__ import annotations

from scripts.replay_validation.ontology.replay_utils import filter_events, run_climax


def run(limit: int = 10) -> None:
    events = filter_events(run_climax(), "SELLING_CLIMAX").tail(limit)
    print("SELLING CLIMAX EVOLUTION REPLAY")
    print("=" * 60)
    if len(events) == 0:
        print("No SELLING_CLIMAX events detected")
        return

    for _, row in events.iterrows():
        print(
            f"{row.get('timestamp')} decay={row.get('efficiency_decay', 0):.3f} "
            f"resolution={row.get('climax_resolution_behavior')} "
            f"capitulation_decay={row.get('capitulation_decay_rate', 0):.3f}"
        )


if __name__ == "__main__":
    run()
