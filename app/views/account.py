"""Account page: sign in, create an account, and sign out."""

from __future__ import annotations

import time

import streamlit as st
from shared import (
    current_account,
    hero,
    show_db_failure,
    sign_in_session,
    sign_out_session,
)

from cronus.accounts import authenticate, create_account
from cronus.config import Settings, get_settings
from cronus.db import session_scope
from cronus.schemas import AccountInfo, DuplicateAccount

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def _load_settings() -> Settings | None:
    try:
        return get_settings()
    except Exception:
        st.error(
            "ChurnLab is not configured. Copy `.env.example` to `.env` and provide "
            "`DATABASE_URL` and `DIRECT_URL`. No credentials are displayed."
        )
        return None


def _record_failure() -> None:
    attempts = int(st.session_state.get("account_failed_attempts", 0)) + 1
    if attempts >= MAX_ATTEMPTS:
        st.session_state["account_failed_attempts"] = 0
        st.session_state["account_lock_until"] = time.time() + LOCK_SECONDS
        st.error(f"Too many failed attempts. Sign-in is locked for {LOCK_SECONDS} seconds.")
        return

    st.session_state["account_failed_attempts"] = attempts
    st.error(
        "Email, username, or password is incorrect. "
        f"{MAX_ATTEMPTS - attempts} attempt(s) remain before a temporary lock."
    )


def _render_sign_in() -> None:
    lock_until = float(st.session_state.get("account_lock_until", 0.0))
    remaining = lock_until - time.time()
    if remaining > 0:
        st.error(f"Too many failed attempts. Sign-in is locked for {remaining:.0f} more seconds.")
        return

    with st.form("account-signin", clear_on_submit=False):
        identifier = st.text_input(
            "Email or username",
            key="account-signin-identifier",
            placeholder="you@example.com or admin",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="account-signin-password",
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if not submitted:
        return
    if not identifier.strip() or not password:
        st.error("Enter your email or username, and your password.")
        return

    try:
        with session_scope() as session:
            account = authenticate(session, identifier=identifier, password=password)
    except Exception as exc:
        show_db_failure("sign in", exc)
        return

    if account is None:
        _record_failure()
        return

    st.session_state.pop("account_failed_attempts", None)
    st.session_state.pop("account_lock_until", None)
    sign_in_session(account)
    st.session_state["flash_success"] = "Signed in."
    st.rerun()


def _render_create() -> None:
    with st.form("account-create", clear_on_submit=False):
        display_name = st.text_input(
            "Display name",
            key="account-create-name",
            placeholder="Your name",
        )
        username = st.text_input(
            "Username",
            key="account-create-username",
            placeholder="yourusername",
            help=(
                "3 to 40 characters. Start with a letter or digit. "
                "Use lowercase letters, digits, dots, hyphens, or underscores."
            ),
        )
        email = st.text_input(
            "Email",
            key="account-create-email",
            placeholder="you@example.com",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="account-create-password",
            help="12 to 128 characters. Use a unique password.",
        )
        confirmation = st.text_input(
            "Confirm password",
            type="password",
            key="account-create-confirm",
        )
        submitted = st.form_submit_button("Create account", type="primary")

    st.caption("No verification email is sent. Use an address you can remember.")

    if not submitted:
        return
    if password != confirmation:
        st.error("The passwords do not match.")
        return
    if not username.strip():
        st.error("Enter a username.")
        return

    try:
        with session_scope() as session:
            account = create_account(
                session,
                email=email,
                display_name=display_name,
                password=password,
                username=username.strip(),
            )
    except DuplicateAccount:
        st.error("That email or username already has an account. Sign in instead.")
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        show_db_failure("create the account", exc)
        return

    sign_in_session(account)
    st.session_state["flash_success"] = "Account created. You are signed in."
    st.rerun()


def _render_signed_in(account: AccountInfo) -> None:
    st.success(f"Signed in as {account.display_name}.")
    if account.is_admin:
        st.info("Administrator account. The Admin page opens without a second password.")
    if account.username is not None:
        st.markdown(f"**Username:** `{account.username}`")
    st.markdown(f"**Email:** {account.email}")
    st.markdown(f"**Member since:** {account.created_at:%d %b %Y}")

    if account.last_login_at is not None:
        st.caption(f"Last sign-in: {account.last_login_at:%d %b %Y %H:%M} UTC")

    st.caption("Use the sidebar to open the dashboard pages.")
    st.divider()

    if st.button("Sign out", type="primary", key="account-signout-page"):
        sign_out_session()
        st.rerun()


def render() -> None:
    hero(
        "Account",
        "Telecom Customer Churn Intelligence/Analysis System. Sign in to open the dashboard.",
        eyebrow="Secure access",
        chips=("Local accounts",),
    )

    if st.session_state.pop("account_expired", False):
        st.warning("Your session expired. Sign in again.")

    account = current_account()
    if account is not None:
        _render_signed_in(account)
        return

    settings = _load_settings()
    if settings is None:
        return

    sign_in_tab, create_tab = st.tabs(["Sign in", "Create account"])
    with sign_in_tab:
        _render_sign_in()
    with create_tab:
        if settings.allow_signup:
            _render_create()
        else:
            st.info("Sign-up is closed. Ask the project owner for an account.")
