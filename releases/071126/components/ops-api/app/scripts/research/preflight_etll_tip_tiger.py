#!/usr/bin/env python3
"""Preflight MaksTiger + symlink local June tick pack → Tiger.

Hard rules: never keep Vision zips / hour parquet on system disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIGER_PACK = Path("/Volumes/MaksTiger/btc-ml/research/etll_tip/tick_pack_202606")
DEFAULT_LOCAL_LINK = (
    ROOT
    / "data/research/external_traders/market_pack_btc_m15/stp2_pilot/tick_pack_202606"
)
DEFAULT_REQUIRE_VOLUME = Path("/Volumes/MaksTiger")
DEFAULT_AUDIT = ROOT / "output/audits/etll_lived_replay_20260825/volume_fidelity/tip_june"
EXPECTED_HOURS = 840  # 2026-05-28 → 2026-07-02


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _free_gib(path: Path) -> float:
    st = os.statvfs(path)
    return (st.f_bavail * st.f_frsize) / (1024**3)


def preflight(*, volume: Path, min_free_gb: float, pack: Path) -> dict:
    if not volume.exists():
        raise SystemExit(f"REQUIRED_VOLUME_NOT_MOUNTED: {volume}")
    free = _free_gib(volume)
    if free < min_free_gb:
        raise SystemExit(
            f"INSUFFICIENT_FREE_SPACE: {volume} has {free:.1f} GiB free; need >={min_free_gb}"
        )
    manifest = pack / "tick_pack_manifest.json"
    agg = pack / "repo/data/raw_market_events_v2/agg_trade"
    hour_dirs = list(agg.glob("date=*/hour=*")) if agg.exists() else []
    status = {
        "generated_at": _utc_now(),
        "volume": str(volume),
        "free_gib": round(free, 2),
        "pack": str(pack),
        "manifest_exists": manifest.exists(),
        "hour_partitions": len(hour_dirs),
        "expected_hours": EXPECTED_HOURS,
    }
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        status["manifest_status"] = m.get("status")
        status["hour_partitions_present"] = (m.get("write_stats") or {}).get(
            "hour_partitions_present"
        )
        status["hour_coverage_pct"] = m.get("hour_coverage_pct")
    return status


def ensure_symlink(*, local_link: Path, tiger_pack: Path) -> dict:
    if not tiger_pack.exists():
        raise SystemExit(f"TIGER_PACK_MISSING: {tiger_pack}")
    local_link.parent.mkdir(parents=True, exist_ok=True)
    if local_link.is_symlink():
        current = local_link.resolve()
        if current == tiger_pack.resolve():
            return {"action": "already_linked", "link": str(local_link), "target": str(tiger_pack)}
        local_link.unlink()
    elif local_link.exists():
        # Refuse to delete a real local directory with data — operator must relocate first.
        size_hint = sum(1 for _ in local_link.rglob("*"))
        raise SystemExit(
            f"LOCAL_PACK_IS_REAL_DIR (entries≈{size_hint}): move/remove before symlink: {local_link}"
        )
    local_link.symlink_to(tiger_pack)
    return {"action": "linked", "link": str(local_link), "target": str(tiger_pack)}


def verify_loader(*, repo: Path, from_ts: str, to_ts: str) -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from btc_ml.trading.shadow_structural_protection.trades import load_agg_trades

    start = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
    end = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
    sample = load_agg_trades(repo=repo, start=start, end=end)
    return {"rows": int(len(sample)), "repo": str(repo)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tiger-pack", type=Path, default=DEFAULT_TIGER_PACK)
    parser.add_argument("--local-link", type=Path, default=DEFAULT_LOCAL_LINK)
    parser.add_argument("--require-volume", type=Path, default=DEFAULT_REQUIRE_VOLUME)
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    parser.add_argument("--symlink", action="store_true", help="Create/repair local → Tiger symlink")
    parser.add_argument("--verify-loader", action="store_true")
    parser.add_argument("--from", dest="from_ts", default="2026-05-28T00:00:00Z")
    parser.add_argument("--to", dest="to_ts", default="2026-05-28T02:00:00Z")
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()

    status = preflight(
        volume=args.require_volume, min_free_gb=float(args.min_free_gb), pack=args.tiger_pack
    )
    if args.require_ready:
        hours = int(status.get("hour_partitions_present") or status.get("hour_partitions") or 0)
        mstat = status.get("manifest_status")
        if mstat != "TICK_PACK_READY" and hours < EXPECTED_HOURS:
            raise SystemExit(
                f"PACK_NOT_READY: status={mstat} hours={hours} expected={EXPECTED_HOURS}"
            )

    link_info = None
    if args.symlink:
        link_info = ensure_symlink(local_link=args.local_link, tiger_pack=args.tiger_pack)
        status["symlink"] = link_info

    loader_info = None
    if args.verify_loader:
        repo = args.tiger_pack / "repo"
        loader_info = verify_loader(repo=repo, from_ts=args.from_ts, to_ts=args.to_ts)
        status["loader_sample"] = loader_info

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / "preflight_tiger_symlink.json"
    out.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
