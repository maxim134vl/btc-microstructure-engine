import json
from pathlib import Path

from btc_ml.trading.intrabar_paper.execution_market_wal import ExecutionMarketWAL


def test_startup_and_replay_stream_wal_without_read_text(tmp_path, monkeypatch):
    wal_root = tmp_path / "execution_market_wal"
    wal_root.mkdir()
    events = wal_root / "events.jsonl"
    events.write_text(
        "".join(
            json.dumps({"wal_offset": offset, "event_type": "BOOK_TICKER"}) + "\n"
            for offset in range(1, 10_001)
        )
        + "torn final line",
        encoding="utf-8",
    )

    original_read_text = Path.read_text

    def reject_wal_read_text(path, *args, **kwargs):
        if path == events:
            raise AssertionError("events.jsonl must be streamed, not materialized")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_wal_read_text)

    wal = ExecutionMarketWAL(wal_root, paper_epoch_id="epoch")

    assert wal.last_offset == 10_000
    assert [row["wal_offset"] for row in wal.iter_from_offset(9_997)] == [9_998, 9_999, 10_000]
