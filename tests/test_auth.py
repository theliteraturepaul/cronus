"""Administrator password verification tests."""

from __future__ import annotations

from cronus.auth import verify_admin_password


def test_correct_password_is_accepted() -> None:
    assert verify_admin_password("correct horse battery staple", "correct horse battery staple")


def test_wrong_password_is_rejected() -> None:
    assert not verify_admin_password("wrong", "correct horse battery staple")


def test_comparison_is_case_sensitive() -> None:
    assert not verify_admin_password("Secret", "secret")


def test_empty_candidate_is_rejected() -> None:
    assert not verify_admin_password("", "secret")


def test_unconfigured_password_fails_closed() -> None:
    assert not verify_admin_password("anything", None)


def test_empty_configured_password_fails_closed() -> None:
    assert not verify_admin_password("anything", "")


def test_non_ascii_password_is_supported() -> None:
    assert verify_admin_password("pässwörd-✓", "pässwörd-✓")


def test_leading_and_trailing_spaces_are_significant() -> None:
    assert verify_admin_password(" secret ", "secret") is False
    assert verify_admin_password(" secret ", " secret ")
