"""Replay STOPPING_VOLUME post-event behavioral evolution."""

from __future__ import annotations

from scripts.replay_validation.ontology.replay_utils import filter_events, run_climax


def run(limit: int = 10) -> None:
    events = filter_events(run_climax(), "STOPPING_VOLUME").tail(limit)
    print("STOPPING VOLUME EVOLUTION REPLAY")
    print("=" * 60)
    if len(events) == 0:
        print("No STOPPING_VOLUME events detected")
        return

    for _, row in events.iterrows():
        print(
            f"{row.get('timestamp')} decay={row.get('efficiency_decay', 0):.3f} "
            f"resolution={row.get('climax_resolution_behavior')} "
            f"absorption_persistence={row.get('absorption_persistence_score', 0):.3f}"
        )


if __name__ == "__main__":
    run()
