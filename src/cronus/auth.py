"""Administrator authentication for the Streamlit application."""

from __future__ import annotations

import hmac


def verify_admin_password(candidate: str, expected: str | None) -> bool:
    """Return True only when a configured password matches exactly.

    The comparison uses :func:`hmac.compare_digest` so the check does not leak
    timing information.  An unset, blank, or empty expected value always fails
    closed.  The function never logs either value.
    """

    if expected is None or not expected:
        return False
    if not candidate:
        return False

    return hmac.compare_digest(
        candidate.encode("utf-8"),
        expected.encode("utf-8"),
    )
