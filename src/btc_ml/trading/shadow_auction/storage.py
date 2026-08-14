"""AES0 storage foundation: mount/local validation, atomic writes, no silent fallback."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from . import (
    SHADOW_REFUSED,
    STORAGE_INSUFFICIENT_SPACE,
    STORAGE_NOT_MOUNTED,
    STORAGE_NOT_WRITABLE,
    STORAGE_UNAVAILABLE,
)
from .paths import (
    REPO_LOCAL_RELATIVE,
    REQUIRED_SUBDIRS,
    assert_shadow_write_path,
    forbidden_persistent_roots,
    repo_root,
    resolve_data_root,
    storage_mode,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StorageValidation:
    ok: bool
    data_root: Path
    volume_root: Path
    storage_mounted: bool
    storage_writable: bool
    storage_free_bytes: int | None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "data_root": str(self.data_root),
            "volume_root": str(self.volume_root),
            "storage_mounted": self.storage_mounted,
            "storage_writable": self.storage_writable,
            "storage_free_bytes": self.storage_free_bytes,
            "error": self.error,
            "details": dict(self.details),
        }


def is_real_mounted_volume(volume_root: Path | str) -> bool:
    """True only when volume_root is a real mount point, not a plain directory.

    Guards against: SSD unplugged → mkdir /Volumes/MaksTiger → local writes.
    """
    root = Path(volume_root).expanduser()
    if not root.exists():
        return False
    try:
        resolved = root.resolve()
    except OSError:
        return False
    if not os.path.ismount(str(resolved)):
        return False
    try:
        vol_dev = os.stat(resolved).st_dev
        sys_dev = os.stat("/").st_dev
    except OSError:
        return False
    if vol_dev == sys_dev:
        return False
    return True


def free_bytes(path: Path | str) -> int | None:
    try:
        st = os.statvfs(str(path))
    except OSError:
        return None
    return int(st.f_bavail) * int(st.f_frsize)


def probe_atomic_write(directory: Path) -> tuple[bool, str | None]:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        fd, tmp_name = tempfile.mkstemp(prefix=".aes_probe_", dir=str(directory))
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(b"aes-storage-probe\n")
                fh.flush()
                os.fsync(fh.fileno())
            final = directory / ".aes_probe_ok"
            os.replace(tmp_name, final)
            final.unlink(missing_ok=True)
        finally:
            if os.path.exists(tmp_name):
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
        return True, None
    except OSError as exc:
        return False, str(exc)


def _refuse(
    *,
    data: Path,
    volume: Path,
    error: str,
    details: dict[str, Any],
    mounted: bool = False,
    writable: bool = False,
    avail: int | None = None,
) -> StorageValidation:
    return StorageValidation(
        ok=False,
        data_root=data,
        volume_root=volume,
        storage_mounted=mounted,
        storage_writable=writable,
        storage_free_bytes=avail,
        error=error,
        details=details,
    )


def validate_repo_local_storage(
    *,
    data_root: Path | str,
    min_free_bytes: int = 0,
    repo: Path | None = None,
) -> StorageValidation:
    """Fail-closed validation for repo-local Auction storage (Docker/VPS/host)."""
    root = (repo or repo_root()).resolve()
    data = Path(data_root).expanduser()
    if not data.is_absolute():
        data = (root / data).resolve()
    else:
        data = data.resolve()
    expected = (root / REPO_LOCAL_RELATIVE).resolve()
    volume = root  # no external volume in this mode
    details: dict[str, Any] = {
        "checked_at": _utc_now(),
        "repo_root": str(root),
        "storage_mode": "repo_local",
        "expected_data_root": str(expected),
    }

    try:
        data.relative_to(expected)
    except ValueError:
        return _refuse(
            data=data,
            volume=volume,
            error=(
                f"{SHADOW_REFUSED}: repo_local data_root must be under {expected} "
                f"(got {data})"
            ),
            details=details,
        )

    for forbidden in forbidden_persistent_roots(root):
        try:
            data.relative_to(forbidden)
            return _refuse(
                data=data,
                volume=volume,
                error=f"{SHADOW_REFUSED}: data_root collides with forbidden root {forbidden}",
                details=details,
            )
        except ValueError:
            continue

    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _refuse(
            data=data,
            volume=volume,
            error=f"{STORAGE_NOT_WRITABLE}: cannot create data_root: {exc}",
            details=details,
            mounted=True,
        )

    writable, write_err = probe_atomic_write(data)
    avail = free_bytes(data)
    details["atomic_probe_error"] = write_err
    if not writable:
        return _refuse(
            data=data,
            volume=volume,
            error=f"{STORAGE_NOT_WRITABLE}: {write_err}",
            details=details,
            mounted=True,
            avail=avail,
        )

    if min_free_bytes and avail is not None and avail < int(min_free_bytes):
        return _refuse(
            data=data,
            volume=volume,
            error=f"{STORAGE_INSUFFICIENT_SPACE}: free={avail} required={min_free_bytes}",
            details=details,
            mounted=True,
            writable=True,
            avail=avail,
        )

    return StorageValidation(
        ok=True,
        data_root=data,
        volume_root=volume,
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=avail,
        error=None,
        details=details,
    )


def validate_external_storage(
    *,
    data_root: Path | str,
    volume_root: Path | str,
    min_free_bytes: int = 0,
    repo: Path | None = None,
) -> StorageValidation:
    """Fail-closed validation for legacy external-volume Shadow Auction storage."""
    data = Path(data_root).expanduser()
    volume = Path(volume_root).expanduser()
    details: dict[str, Any] = {
        "checked_at": _utc_now(),
        "repo_root": str((repo or repo_root()).resolve()),
        "storage_mode": "external_volume",
    }

    # Hard refuse data_root inside the repo for external mode.
    try:
        data.resolve().relative_to((repo or repo_root()).resolve())
        return _refuse(
            data=data,
            volume=volume,
            error=f"{SHADOW_REFUSED}: external data_root must not be inside the repository",
            details=details,
        )
    except ValueError:
        pass

    for forbidden in forbidden_persistent_roots(repo or repo_root()):
        try:
            data.expanduser().resolve(strict=False).relative_to(forbidden)
            return _refuse(
                data=data,
                volume=volume,
                error=f"{SHADOW_REFUSED}: data_root collides with forbidden root {forbidden}",
                details=details,
            )
        except ValueError:
            continue

    if not volume.exists():
        return _refuse(
            data=data,
            volume=volume,
            error=f"{STORAGE_UNAVAILABLE}: volume root missing: {volume}",
            details=details,
        )

    mounted = is_real_mounted_volume(volume)
    details["ismount"] = mounted
    if not mounted:
        return _refuse(
            data=data,
            volume=volume,
            error=(
                f"{STORAGE_NOT_MOUNTED}: {volume} is not a real mounted filesystem "
                "(refusing plain local directory)"
            ),
            details=details,
        )

    try:
        data.expanduser().resolve(strict=False).relative_to(volume.resolve())
    except ValueError:
        return _refuse(
            data=data,
            volume=volume,
            mounted=True,
            error=f"{SHADOW_REFUSED}: data_root {data} is outside volume {volume}",
            details=details,
        )

    try:
        data.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _refuse(
            data=data,
            volume=volume,
            mounted=True,
            avail=free_bytes(volume),
            error=f"{STORAGE_NOT_WRITABLE}: cannot create data_root: {exc}",
            details=details,
        )

    writable, write_err = probe_atomic_write(data)
    avail = free_bytes(data if data.exists() else volume)
    details["atomic_probe_error"] = write_err
    if not writable:
        return _refuse(
            data=data,
            volume=volume,
            mounted=True,
            avail=avail,
            error=f"{STORAGE_NOT_WRITABLE}: {write_err}",
            details=details,
        )

    if min_free_bytes and avail is not None and avail < int(min_free_bytes):
        return _refuse(
            data=data,
            volume=volume,
            mounted=True,
            writable=True,
            avail=avail,
            error=f"{STORAGE_INSUFFICIENT_SPACE}: free={avail} required={min_free_bytes}",
            details=details,
        )

    return StorageValidation(
        ok=True,
        data_root=data.resolve(),
        volume_root=volume.resolve(),
        storage_mounted=True,
        storage_writable=True,
        storage_free_bytes=avail,
        error=None,
        details=details,
    )


def validate_storage(
    config: Mapping[str, Any],
    *,
    repo: Path | None = None,
) -> StorageValidation:
    """Validate Auction storage according to ``storage_mode`` in config."""
    root = repo or repo_root()
    mode = storage_mode(config)
    data = resolve_data_root(config, repo=root)
    min_free = int(config.get("min_free_bytes") or 0)
    if mode == "repo_local":
        return validate_repo_local_storage(
            data_root=data,
            min_free_bytes=min_free,
            repo=root,
        )
    volume = config.get("required_volume_root")
    if not volume:
        return _refuse(
            data=data,
            volume=Path("."),
            error=f"{SHADOW_REFUSED}: required_volume_root is required for external_volume mode",
            details={"storage_mode": mode},
        )
    return validate_external_storage(
        data_root=data,
        volume_root=volume,
        min_free_bytes=min_free,
        repo=root,
    )


def ensure_layout(data_root: Path | str, *, repo: Path | None = None) -> dict[str, Path]:
    root = assert_shadow_write_path(Path(data_root), data_root=data_root, repo=repo)
    root.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {"root": root}
    for name in REQUIRED_SUBDIRS:
        path = assert_shadow_write_path(root / name, data_root=root, repo=repo)
        path.mkdir(parents=True, exist_ok=True)
        out[name] = path
    return out


def atomic_write_json(
    path: Path | str,
    payload: Mapping[str, Any],
    *,
    data_root: Path | str,
    repo: Path | None = None,
) -> Path:
    target = assert_shadow_write_path(path, data_root=data_root, repo=repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(dict(payload), fh, indent=2, sort_keys=True, default=str)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    return target


def append_jsonl(
    path: Path | str,
    row: Mapping[str, Any],
    *,
    data_root: Path | str,
    repo: Path | None = None,
) -> Path:
    target = assert_shadow_write_path(path, data_root=data_root, repo=repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(dict(row), ensure_ascii=True, separators=(",", ":"), default=str) + "\n"
    with target.open("a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return target


class ShadowAuctionStore:
    """Minimal AES0 store confined to the validated Auction root."""

    def __init__(
        self,
        *,
        data_root: Path | str,
        volume_root: Path | str | None = None,
        min_free_bytes: int = 0,
        repo: Path | None = None,
        storage_mode_name: str | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.repo = repo or repo_root()
        if config is not None:
            self.validation = validate_storage(config, repo=self.repo)
        elif storage_mode_name == "repo_local" or volume_root is None:
            self.validation = validate_repo_local_storage(
                data_root=data_root,
                min_free_bytes=min_free_bytes,
                repo=self.repo,
            )
        else:
            self.validation = validate_external_storage(
                data_root=data_root,
                volume_root=volume_root,
                min_free_bytes=min_free_bytes,
                repo=self.repo,
            )
        if not self.validation.ok:
            raise RuntimeError(self.validation.error or STORAGE_UNAVAILABLE)
        self.data_root = self.validation.data_root
        self.volume_root = self.validation.volume_root
        self.layout = ensure_layout(self.data_root, repo=self.repo)
        self.write_errors = 0

    def write_json(self, relative: str, payload: Mapping[str, Any]) -> Path:
        try:
            return atomic_write_json(
                self.data_root / relative,
                payload,
                data_root=self.data_root,
                repo=self.repo,
            )
        except Exception:
            self.write_errors += 1
            raise

    def append_jsonl(self, relative: str, row: Mapping[str, Any]) -> Path:
        try:
            return append_jsonl(
                self.data_root / relative,
                row,
                data_root=self.data_root,
                repo=self.repo,
            )
        except Exception:
            self.write_errors += 1
            raise
