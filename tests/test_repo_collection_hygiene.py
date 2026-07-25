"""Repository hygiene: canonical pytest collection must stay bounded.

Guards against reintroducing the archive_removed import-time hang
(historical_liquidation_test.py running pct_change at module import).
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYTEST_INI = ROOT / "pytest.ini"


def test_pytest_ini_exists_with_canonical_testpaths():
    assert PYTEST_INI.is_file()
    text = PYTEST_INI.read_text(encoding="utf-8")
    assert "testpaths" in text
    assert "tests" in text
    assert "archive_removed" in text
    assert "norecursedirs" in text


def test_archive_removed_is_not_under_testpaths():
    """Active collection root must not nest the archived tree."""
    archived = ROOT / "archive_removed"
    tests_root = ROOT / "tests"
    assert tests_root.is_dir()
    if archived.exists():
        assert archived.resolve() != tests_root.resolve()
        assert archived.resolve() not in tests_root.resolve().parents
        # archived must not be a child of tests/
        assert not str(archived.resolve()).startswith(str(tests_root.resolve()) + "/")


@pytest.mark.parametrize(
    "forbidden_name",
    ["historical_liquidation_test.py"],
)
def test_hanging_archive_modules_are_outside_tests(forbidden_name: str):
    hits = list((ROOT / "tests").rglob(forbidden_name))
    assert hits == []
