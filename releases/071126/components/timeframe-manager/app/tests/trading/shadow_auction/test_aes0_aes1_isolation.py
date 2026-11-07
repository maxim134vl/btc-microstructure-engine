"""AES0/AES1 isolation, storage, watermark, and contract tests."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest import mock

import pytest

from btc_ml.trading.shadow_auction import (
    SHADOW_REFUSED,
    STORAGE_NOT_MOUNTED,
    STORAGE_NOT_WRITABLE,
    STORAGE_UNAVAILABLE,
    WRITE_BOUNDARY_VIOLATION,
)
from btc_ml.trading.shadow_auction.cache import BoundedCache
from btc_ml.trading.shadow_auction.contract import (
    build_contract,
    compute_logic_fingerprint,
    load_config,
)
from btc_ml.trading.shadow_auction.paths import assert_shadow_write_path
from btc_ml.trading.shadow_auction.runtime import ShadowAuctionRuntime, refuse_without_storage
from btc_ml.trading.shadow_auction.storage import (
    ShadowAuctionStore,
    is_real_mounted_volume,
    validate_external_storage,
)


REPO = Path(__file__).resolve().parents[3]
REAL_VOLUME = Path("/Volumes/MaksTiger")
REAL_DATA_ROOT = REAL_VOLUME / "btc-ml" / "shadow_auction"


def _cfg(tmp_path: Path, **overrides) -> Path:
    raw = json.loads((REPO / "config" / "shadow_auction.json").read_text(encoding="utf-8"))
    raw.update(overrides)
    path = tmp_path / "shadow_auction.json"
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return path


def test_01_external_storage_mounted_pass():
    if not REAL_VOLUME.exists() or not is_real_mounted_volume(REAL_VOLUME):
        pytest.skip("MaksTiger volume not mounted")
    result = validate_external_storage(
        data_root=REAL_DATA_ROOT,
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    assert result.ok is True
    assert result.storage_mounted is True
    assert result.storage_writable is True
    assert result.storage_free_bytes is not None
    assert result.storage_free_bytes > 0
    store = ShadowAuctionStore(
        data_root=REAL_DATA_ROOT,
        volume_root=REAL_VOLUME,
        min_free_bytes=1024,
        repo=REPO,
    )
    for name in ("memory", "manifests", "logs", "health", "replay", "archive"):
        assert (store.data_root / name).is_dir()


def test_02_external_storage_unavailable_refuses(tmp_path: Path):
    missing = tmp_path / "no_such_volume"
    result = validate_external_storage(
        data_root=missing / "shadow_auction",
        volume_root=missing,
        repo=REPO,
    )
    assert result.ok is False
    assert STORAGE_UNAVAILABLE in (result.error or "")
    gate = refuse_without_storage(
        repo=REPO,
        config_path=_cfg(
            tmp_path,
            data_root=str(missing / "shadow_auction"),
            required_volume_root=str(missing),
        ),
    )
    assert gate["ok"] is False
    assert gate["canonical_unaffected"] is True
    assert gate["status"] == SHADOW_REFUSED


def test_03_fake_local_volumes_directory_rejected(tmp_path: Path):
    fake_vol = tmp_path / "Volumes" / "MaksTiger"
    fake_vol.mkdir(parents=True)
    fake_root = fake_vol / "btc-ml" / "shadow_auction"
    fake_root.mkdir(parents=True)
    assert is_real_mounted_volume(fake_vol) is False
    result = validate_external_storage(
        data_root=fake_root,
        volume_root=fake_vol,
        repo=REPO,
    )
    assert result.ok is False
    assert STORAGE_NOT_MOUNTED in (result.error or "")
    assert "plain local directory" in (result.error or "")


def test_04_readonly_storage_safe_failure(tmp_path: Path):
    vol = tmp_path / "vol"
    data = vol / "shadow"
    data.mkdir(parents=True)
    # Pretend mounted, then make unwritable.
    with mock.patch(
        "btc_ml.trading.shadow_auction.storage.is_real_mounted_volume",
        return_value=True,
    ):
        os.chmod(data, stat.S_IRUSR | stat.S_IXUSR)
        try:
            result = validate_external_storage(
                data_root=data,
                volume_root=vol,
                repo=REPO,
            )
            assert result.ok is False
            assert STORAGE_NOT_WRITABLE in (result.error or "")
        finally:
            os.chmod(data, stat.S_IRWXU)


def test_05_duplicate_source_event_no_duplicate_write(tmp_path: Path):
    vol = tmp_path / "ssd"
    root = vol / "shadow_auction"
    root.mkdir(parents=True)
    with mock.patch(
        "btc_ml.trading.shadow_auction.storage.is_real_mounted_volume",
        return_value=True,
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.free_bytes",
        return_value=10**12,
    ):
        # Bypass device inequality by also patching validate's mount check only.
        with mock.patch(
            "btc_ml.trading.shadow_auction.storage.is_real_mounted_volume",
            return_value=True,
        ):
            # Force volume device check pass: patch whole validate mount path
            original = is_real_mounted_volume
            assert original  # keep import used
            store = None
            # Monkeypatch validate to treat tmp as mounted writable volume
            with mock.patch(
                "btc_ml.trading.shadow_auction.runtime.validate_storage"
            ) as vmock:
                from btc_ml.trading.shadow_auction.storage import StorageValidation

                vmock.return_value = StorageValidation(
                    ok=True,
                    data_root=root.resolve(),
                    volume_root=vol.resolve(),
                    storage_mounted=True,
                    storage_writable=True,
                    storage_free_bytes=10**12,
                )
                # Also need ShadowAuctionStore constructor validation
                with mock.patch(
                    "btc_ml.trading.shadow_auction.storage.validate_external_storage",
                    return_value=vmock.return_value,
                ):
                    cfg = _cfg(
                        tmp_path,
                        data_root=str(root),
                        required_volume_root=str(vol),
                        min_free_bytes=0,
                    )
                    rt = ShadowAuctionRuntime.bootstrap(repo=REPO, config_path=cfg)
                    store = rt.store
                    a = rt.ingest_source_event(
                        source_event_id="EVT_1",
                        source_timestamp="2026-08-11T10:00:00Z",
                    )
                    b = rt.ingest_source_event(
                        source_event_id="EVT_1",
                        source_timestamp="2026-08-11T10:00:00Z",
                    )
    assert a["accepted"] is True
    assert b["accepted"] is False
    assert b["reason"] == "DUPLICATE"
    journal = root / "memory" / "source_ingest.jsonl"
    lines = [ln for ln in journal.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 1


def test_06_out_of_order_event_records_violation(tmp_path: Path):
    vol = tmp_path / "ssd"
    root = vol / "shadow_auction"
    root.mkdir(parents=True)
    from btc_ml.trading.shadow_auction.storage import StorageValidation

    ok = StorageValidation(
        ok=True,
        data_root=root.resolve(),
        volume_root=vol.resolve(),
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=10**12,
    )
    with mock.patch(
        "btc_ml.trading.shadow_auction.runtime.validate_storage",
        return_value=ok,
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.validate_external_storage",
        return_value=ok,
    ):
        cfg = _cfg(tmp_path, data_root=str(root), required_volume_root=str(vol), min_free_bytes=0)
        rt = ShadowAuctionRuntime.bootstrap(repo=REPO, config_path=cfg)
        rt.ingest_source_event(source_event_id="EVT_A", source_timestamp="2026-08-11T12:00:00Z")
        result = rt.ingest_source_event(
            source_event_id="EVT_B",
            source_timestamp="2026-08-11T11:00:00Z",
        )
    assert result["accepted"] is True
    assert result["reason"] == "ORDERING_VIOLATION"
    assert rt.watermark.state.ordering_violations == 1


def test_07_restart_from_watermark_no_duplicate(tmp_path: Path):
    vol = tmp_path / "ssd"
    root = vol / "shadow_auction"
    root.mkdir(parents=True)
    from btc_ml.trading.shadow_auction.storage import StorageValidation

    ok = StorageValidation(
        ok=True,
        data_root=root.resolve(),
        volume_root=vol.resolve(),
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=10**12,
    )
    with mock.patch(
        "btc_ml.trading.shadow_auction.runtime.validate_storage",
        return_value=ok,
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.validate_external_storage",
        return_value=ok,
    ):
        cfg = _cfg(tmp_path, data_root=str(root), required_volume_root=str(vol), min_free_bytes=0)
        rt1 = ShadowAuctionRuntime.bootstrap(repo=REPO, config_path=cfg)
        rt1.ingest_source_event(source_event_id="EVT_R", source_timestamp="2026-08-11T13:00:00Z")
        rt2 = ShadowAuctionRuntime.bootstrap(repo=REPO, config_path=cfg)
        again = rt2.ingest_source_event(
            source_event_id="EVT_R",
            source_timestamp="2026-08-11T13:00:00Z",
        )
    assert again["accepted"] is False
    assert again["reason"] == "DUPLICATE"
    lines = (root / "memory" / "source_ingest.jsonl").read_text(encoding="utf-8").splitlines()
    assert len([ln for ln in lines if ln.strip()]) == 1


def test_08_bounded_cache_does_not_grow_forever():
    cache = BoundedCache(max_items=8)
    for i in range(100):
        cache.set(f"k{i}", i)
    assert len(cache) == 8
    assert "k99" in cache
    assert "k0" not in cache


def test_09_shadow_crash_does_not_affect_canonical(tmp_path: Path):
    # Canonical paper config remains readable and unchanged after Shadow refuse.
    paper_cfg = REPO / "config" / "intrabar_paper_execution.json"
    before = paper_cfg.read_text(encoding="utf-8")
    missing = tmp_path / "gone"
    gate = refuse_without_storage(
        repo=REPO,
        config_path=_cfg(
            tmp_path,
            data_root=str(missing / "shadow"),
            required_volume_root=str(missing),
        ),
    )
    assert gate["ok"] is False
    assert gate["canonical_unaffected"] is True
    after = paper_cfg.read_text(encoding="utf-8")
    assert before == after
    # LIVE1B package still importable independently.
    from btc_ml.trading.intrabar_paper import config as paper_config

    assert paper_config is not None


def test_10_shadow_not_required_dependency_of_canonical_execution():
    engine_path = REPO / "src" / "btc_ml" / "trading" / "intrabar_paper" / "engine.py"
    cognition_path = REPO / "scripts" / "live" / "run_intrabar_cognition_service.py"
    paper_mgr = REPO / "scripts" / "live" / "run_intrabar_paper_manager.py"
    for path in (engine_path, cognition_path, paper_mgr):
        text = path.read_text(encoding="utf-8")
        assert "shadow_auction" not in text
        assert "AUCTION_EPISODE_SHADOW" not in text


def test_11_heavy_write_not_in_repo_tree(tmp_path: Path):
    with pytest.raises(RuntimeError) as exc:
        assert_shadow_write_path(
            REPO / "data" / "trading" / "shadow_auction" / "x.json",
            data_root=REPO / "data" / "trading" / "shadow_auction",
            repo=REPO,
        )
    assert WRITE_BOUNDARY_VIOLATION in str(exc.value)

    # Config pointing inside repo must be refused by validate.
    result = validate_external_storage(
        data_root=REPO / "data" / "trading" / "shadow_auction",
        volume_root=REAL_VOLUME if REAL_VOLUME.exists() else tmp_path / "vol",
        repo=REPO,
    )
    assert result.ok is False
    assert "must not be inside the repository" in (result.error or "")


def test_12_manifest_fingerprint_persisted(tmp_path: Path):
    vol = tmp_path / "ssd"
    root = vol / "shadow_auction"
    root.mkdir(parents=True)
    from btc_ml.trading.shadow_auction.storage import StorageValidation

    ok = StorageValidation(
        ok=True,
        data_root=root.resolve(),
        volume_root=vol.resolve(),
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=10**12,
    )
    expected_fp = compute_logic_fingerprint()
    with mock.patch(
        "btc_ml.trading.shadow_auction.runtime.validate_storage",
        return_value=ok,
    ), mock.patch(
        "btc_ml.trading.shadow_auction.storage.validate_external_storage",
        return_value=ok,
    ):
        cfg = _cfg(tmp_path, data_root=str(root), required_volume_root=str(vol), min_free_bytes=0)
        rt = ShadowAuctionRuntime.bootstrap(repo=REPO, config_path=cfg)
    manifest = json.loads((root / "manifests" / "contract.json").read_text(encoding="utf-8"))
    health = json.loads((root / "health" / "health.json").read_text(encoding="utf-8"))
    assert manifest["shadow_name"] == "AUCTION_EPISODE_SHADOW"
    assert manifest["logic_version"] == "AES_V1"
    assert manifest["schema_version"] == 1
    assert manifest["observer_only"] is True
    assert manifest["enforcement_enabled"] is False
    assert manifest["logic_fingerprint"] == expected_fp
    assert health["logic_fingerprint"] == expected_fp
    assert health["observer_only"] is True
    assert health["enforcement_enabled"] is False
    assert health["data_root"] == str(root.resolve())


def test_contract_rejects_enforcement_enabled():
    with pytest.raises(ValueError):
        build_contract(config={"observer_only": True, "enforcement_enabled": True})
    with pytest.raises(ValueError):
        build_contract(config={"observer_only": False, "enforcement_enabled": False})


def test_load_repo_config():
    cfg = load_config(repo_root=REPO)
    assert cfg["data_root"] == "/Volumes/MaksTiger/btc-ml/shadow_auction"
    assert cfg["required_volume_root"] == "/Volumes/MaksTiger"
    assert cfg["observer_only"] is True
    assert cfg["enforcement_enabled"] is False
