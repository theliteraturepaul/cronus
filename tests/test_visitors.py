"""Visitor throttle tests that need no database."""

from __future__ import annotations

from cronus.visitors import should_record


def test_first_visit_is_recorded() -> None:
    assert should_record(None, 1_000.0)


def test_visit_inside_the_window_is_skipped() -> None:
    assert not should_record(1_000.0, 1_000.0 + 1_799)


def test_visit_at_the_window_boundary_is_recorded() -> None:
    assert should_record(1_000.0, 1_000.0 + 1_800)


def test_visit_after_the_window_is_recorded() -> None:
    assert should_record(1_000.0, 1_000.0 + 3_600)


def test_non_positive_window_disables_throttling() -> None:
    assert should_record(1_000.0, 1_000.0, window_seconds=0)
    assert should_record(1_000.0, 1_000.0, window_seconds=-1)
