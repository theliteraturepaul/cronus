"""Administrator and account authentication tests."""

from __future__ import annotations

import pytest

from cronus.auth import (
    hash_password,
    hash_visitor_key,
    is_valid_email,
    normalize_email,
    validate_display_name,
    validate_password,
    verify_admin_password,
    verify_password,
)


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


def test_normalize_email_trims_and_casefolds() -> None:
    assert normalize_email("  Paul@Example.COM ") == "paul@example.com"


def test_normalize_email_rejects_blank() -> None:
    with pytest.raises(ValueError, match="email"):
        normalize_email("   ")


@pytest.mark.parametrize(
    "address",
    [
        "paul@example.com",
        "first.last+tag@sub.example.co.uk",
        "a@b.c",
    ],
)
def test_valid_email_is_accepted(address: str) -> None:
    assert is_valid_email(address)


@pytest.mark.parametrize(
    "address",
    [
        "",
        "paul",
        "paul@",
        "@example.com",
        "paul@example",
        "paul @example.com",
        "paul@exa mple.com",
    ],
)
def test_invalid_email_is_rejected(address: str) -> None:
    assert not is_valid_email(address)


def test_display_name_is_stripped() -> None:
    assert validate_display_name("  Paul  ") == "Paul"


def test_display_name_length_is_enforced() -> None:
    with pytest.raises(ValueError, match="2 to 80"):
        validate_display_name("P")
    with pytest.raises(ValueError, match="2 to 80"):
        validate_display_name("P" * 81)


def test_password_policy_accepts_a_long_unique_password() -> None:
    validate_password(
        "correct horse battery staple",
        email="paul@example.com",
        display_name="Paul",
    )


def test_password_policy_rejects_short_passwords() -> None:
    with pytest.raises(ValueError, match="12 to 128"):
        validate_password("short", email="paul@example.com", display_name="Paul")


def test_password_policy_rejects_the_email_address() -> None:
    with pytest.raises(ValueError, match="email address"):
        validate_password(
            "Paul@Example.com",
            email="paul@example.com",
            display_name="Paul",
        )


def test_password_policy_rejects_the_display_name() -> None:
    with pytest.raises(ValueError, match="display name"):
        validate_password(
            "PaulSahitya01",
            email="someone@example.com",
            display_name="PaulSahitya01",
        )


def test_hash_and_verify_round_trip() -> None:
    encoded = hash_password("correct horse battery staple")
    assert encoded.startswith("scrypt$16384$8$1$")
    assert verify_password("correct horse battery staple", encoded)


def test_hash_uses_a_random_salt() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")
    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert verify_password("correct horse battery staple", second)


def test_wrong_password_is_rejected_by_the_hash() -> None:
    encoded = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", encoded)


@pytest.mark.parametrize(
    "encoded",
    [
        None,
        "",
        "plaintext",
        "bcrypt$1$2$3$4$5",
        "scrypt$16384$8$1$not-base64$also-not",
        "scrypt$1$8$1$c2FsdA==$aGFzaA==",
    ],
)
def test_malformed_hashes_are_rejected(encoded: str | None) -> None:
    assert not verify_password("correct horse battery staple", encoded)


def test_empty_password_is_rejected_by_the_hash() -> None:
    with pytest.raises(ValueError):
        hash_password("")


def test_visitor_key_is_stable() -> None:
    first = hash_visitor_key(
        ip="203.0.113.7",
        user_agent="Mozilla/5.0",
        salt="pepper",
        fallback="local",
    )
    second = hash_visitor_key(
        ip="203.0.113.7",
        user_agent="Mozilla/5.0",
        salt="pepper",
        fallback="local",
    )
    assert first == second
    assert len(first) == 32
    assert all(character in "0123456789abcdef" for character in first)


def test_visitor_key_changes_with_the_salt() -> None:
    first = hash_visitor_key(ip="203.0.113.7", user_agent="", salt="one", fallback="local")
    second = hash_visitor_key(ip="203.0.113.7", user_agent="", salt="two", fallback="local")
    assert first != second


def test_visitor_key_uses_the_fallback_without_an_ip() -> None:
    first = hash_visitor_key(ip=None, user_agent="", salt="pepper", fallback="local:a")
    second = hash_visitor_key(ip=None, user_agent="", salt="pepper", fallback="local:b")
    assert first != second


def test_visitor_key_requires_a_salt() -> None:
    with pytest.raises(ValueError, match="salt"):
        hash_visitor_key(ip="203.0.113.7", user_agent="", salt="", fallback="local")
