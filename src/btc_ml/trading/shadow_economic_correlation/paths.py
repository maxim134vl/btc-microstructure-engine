"""Shadow write-boundary paths."""

from __future__ import annotations

from pathlib import Path

from . import WRITE_BOUNDARY_VIOLATION


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def shadow_root(repo: Path | None = None) -> Path:
    return (repo or repo_root()) / "data" / "trading" / "shadow_economic_correlation"


def paper_books_root(repo: Path | None = None, *, epoch_id: str) -> Path:
    return (repo or repo_root()) / "data" / "trading" / "intrabar_paper" / epoch_id / "books"


def assert_shadow_write_path(path: Path, *, repo: Path | None = None) -> Path:
    root = shadow_root(repo).resolve()
    target = Path(path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{WRITE_BOUNDARY_VIOLATION}: refused write to {target}") from exc
    return target
