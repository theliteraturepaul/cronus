"""Shared Streamlit helpers, cached reads, and UI components."""

from __future__ import annotations

import contextlib
import html
import logging
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

from cronus.accounts import ensure_admin_account
from cronus.analytics import filter_current_frame
from cronus.auth import hash_visitor_key
from cronus.config import Settings, get_settings
from cronus.db import check_connection, session_scope
from cronus.modeling import prepare_current_frame
from cronus.modeling.serving import (
    ScoringModel,
    ThresholdPolicy,
    fit_scoring_model,
    score_current_relationships,
)
from cronus.repository import (
    get_active_dataset_summary,
    get_current_relationships,
    list_datasets,
)
from cronus.schemas import (
    AccountInfo,
    ActiveDatasetSummary,
    ConnectionInfo,
    DatasetInfo,
    ValidationReport,
    VisitorSnapshot,
)
from cronus.visitors import (
    read_visitor_snapshot,
    record_visit,
    should_record,
)

logger = logging.getLogger("cronus.app")


@st.cache_data(ttl=60, show_spinner=False)
def load_connection_status() -> ConnectionInfo:
    return check_connection()


@st.cache_data(ttl=60, show_spinner=False)
def load_active_summary() -> ActiveDatasetSummary | None:
    with session_scope() as session:
        return get_active_dataset_summary(session)


@st.cache_data(ttl=60, show_spinner=False)
def load_datasets() -> list[DatasetInfo]:
    with session_scope() as session:
        return list_datasets(session)


@st.cache_data(ttl=60, show_spinner=False)
def load_current_relationships(
    dataset_id: str,
    dataset_version: str,
    expected_rows: int,
) -> pd.DataFrame:
    del dataset_version
    with session_scope() as session:
        frame = get_current_relationships(session, uuid.UUID(dataset_id))
    if len(frame) != expected_rows:
        raise ValueError(
            f"The active dataset returned {len(frame):,} current rows; "
            f"the active summary reported {expected_rows:,}."
        )
    return frame


@st.cache_resource(show_spinner="Fitting the churn model...")
def load_scoring_model(
    dataset_id: str,
    dataset_version: str,
    current_rows: int,
) -> ScoringModel:
    del dataset_version
    with session_scope() as session:
        frame = get_current_relationships(session, uuid.UUID(dataset_id))
    current = prepare_current_frame(frame)
    if len(current) != current_rows:
        raise ValueError(
            f"The active dataset returned {len(current):,} current rows; "
            f"the active summary reported {current_rows:,}."
        )
    return fit_scoring_model(current, dataset_id=dataset_id)


@st.cache_data(ttl=60, show_spinner=False)
def load_scores(
    dataset_id: str,
    dataset_version: str,
    current_rows: int,
    threshold: float,
) -> pd.DataFrame:
    scoring_model = load_scoring_model(dataset_id, dataset_version, current_rows)
    current = load_current_relationships(dataset_id, dataset_version, current_rows)
    return score_current_relationships(scoring_model, current, threshold=threshold)


def dataset_version(summary: ActiveDatasetSummary) -> str:
    return f"{summary.as_of_date.isoformat()}:{summary.current_relationship_count}"


def clear_caches() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


def show_flash() -> None:
    message = st.session_state.pop("flash_success", None)
    if message:
        st.success(message)


MAX_VISITOR_LOG_ENTRIES = 50


def current_account() -> AccountInfo | None:
    """Return the signed-in account, or None when the session is absent or stale."""

    raw = st.session_state.get("account")
    signed_in_at = st.session_state.get("signed_in_at")
    if not isinstance(raw, dict) or not isinstance(signed_in_at, (int, float)):
        return None

    max_hours = 12
    with contextlib.suppress(Exception):
        max_hours = get_settings().session_max_hours

    if time.time() - float(signed_in_at) > max_hours * 3600:
        sign_out_session()
        st.session_state["account_expired"] = True
        return None

    try:
        return AccountInfo.model_validate(raw)
    except Exception:
        sign_out_session()
        return None


def sign_in_session(account: AccountInfo) -> None:
    """Store the account in the browser session."""

    st.session_state["account"] = account.model_dump()
    st.session_state["signed_in_at"] = time.time()
    st.session_state.pop("account_expired", None)


def sign_out_session() -> None:
    """Clear the account, the admin gate, and any pending lock state."""

    for key in (
        "account",
        "signed_in_at",
        "admin_authenticated",
        "account_failed_attempts",
        "account_lock_until",
        "admin_failed_attempts",
        "admin_lock_until",
    ):
        st.session_state.pop(key, None)


def render_guest_sidebar() -> None:
    """Render the sidebar for a visitor who is not signed in."""

    st.sidebar.markdown(
        '<div class="cl-brand">'
        '<span class="cl-brand-mark">CL</span>'
        "<span><strong>ChurnLab</strong><br>"
        '<span class="cl-brand-sub">Telecom churn analysis</span></span>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.sidebar.info("Sign in to open the dashboard.")
    st.sidebar.caption("Accounts are local to this application. No verification email is sent.")
    render_appearance_control()


@st.cache_data(ttl=60, show_spinner=False)
def visitor_snapshot() -> VisitorSnapshot | None:
    """Return the cached visitor counts, or None when the read fails."""

    since = datetime.now(UTC) - timedelta(days=7)
    try:
        with session_scope() as session:
            return read_visitor_snapshot(session, since=since)
    except Exception as exc:
        logger.warning("Visitor counts unavailable: %s", exc)
        return None


def record_current_visit(
    account: AccountInfo | None,
    *,
    settings: Settings | None = None,
) -> None:
    """Record at most one page view per session and page in 30 minutes."""

    resolved = settings
    if resolved is None:
        try:
            resolved = get_settings()
        except Exception:
            return

    salt = resolved.visitor_salt
    if salt is None:
        return

    session_id = _visitor_session_id()
    page_path = _current_page_path()
    now = time.time()

    log = st.session_state.get("visitor_log")
    if not isinstance(log, dict):
        log = {}
    log_key = f"{session_id}:{page_path}"
    if not should_record(log.get(log_key), now):
        return

    log[log_key] = now
    if len(log) > MAX_VISITOR_LOG_ENTRIES:
        stale = sorted(log, key=log.get)[: len(log) - MAX_VISITOR_LOG_ENTRIES]
        for item in stale:
            log.pop(item, None)
    st.session_state["visitor_log"] = log

    visitor_key = hash_visitor_key(
        ip=_client_ip(),
        user_agent=_request_header("User-Agent"),
        salt=salt,
        fallback=f"local:{session_id}",
    )

    try:
        with session_scope() as session:
            record_visit(
                session,
                visitor_key=visitor_key,
                session_id=session_id,
                user_id=account.id if account is not None else None,
                page_path=page_path,
            )
    except Exception as exc:
        logger.warning("Visitor write failed: %s", exc)
        st.session_state["visitor_log"].pop(log_key, None)


def render_visitor_banner(account: AccountInfo | None = None) -> None:
    """Render the site-wide visitor strip. Never block the page on failure."""

    try:
        settings: Settings | None
        try:
            settings = get_settings()
        except Exception:
            settings = None

        recording = settings is not None and settings.visitor_salt is not None
        if recording:
            record_current_visit(account, settings=settings)

        snapshot = visitor_snapshot()
        if snapshot is None:
            return

        st.markdown(
            '<div class="cl-visitor">'
            '<span class="cl-eyebrow">Visitor analytics</span>'
            '<div class="cl-visitor-grid">'
            f"<div><strong>{snapshot.total_visits:,}</strong><span>Total visits</span></div>"
            f"<div><strong>{snapshot.registered_users:,}</strong>"
            "<span>Registered users</span></div>"
            f"<div><strong>{snapshot.active_sessions:,}</strong>"
            "<span>Active sessions</span></div>"
            "</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        if recording:
            st.caption("Anonymous counts. No IP addresses or cookies are stored.")
        else:
            st.caption("Visitor recording is off. Set `VISITOR_HASH_SALT` to start counting.")
    except Exception as exc:
        logger.warning("Visitor banner unavailable: %s", exc)


def _visitor_session_id() -> uuid.UUID:
    raw = st.session_state.get("visitor_session_id")
    if isinstance(raw, str):
        try:
            return uuid.UUID(raw)
        except ValueError:
            pass

    value = uuid.uuid4()
    st.session_state["visitor_session_id"] = str(value)
    return value


def _client_ip() -> str | None:
    try:
        value = st.context.ip_address
    except Exception:
        return None
    return str(value) if value else None


def _request_header(name: str) -> str | None:
    try:
        headers = st.context.headers
    except Exception:
        return None

    try:
        value = headers.get(name)
    except Exception:
        value = None
    if value:
        return str(value)

    try:
        items = headers.items()
    except Exception:
        return None
    for key, item in items:
        if key.casefold() == name.casefold() and item:
            return str(item)
    return None


def _current_page_path() -> str:
    try:
        raw = st.context.url
    except Exception:
        raw = None
    if not raw:
        return "/"
    return urlparse(str(raw)).path or "/"


def show_db_failure(action: str, exc: Exception) -> None:
    logger.exception("Database operation failed: %s", action, exc_info=exc)
    st.error(
        f"Could not {action}. The Neon database may be waking up, or the "
        "connection details in .env may be wrong. No credentials were displayed."
    )


def active_summary_state() -> tuple[ActiveDatasetSummary | None, bool]:
    """Return the active summary and a flag that separates no data from failure."""

    try:
        return load_active_summary(), True
    except Exception as exc:
        show_db_failure("read the active dataset", exc)
        return None, False


def current_frame_for(summary: ActiveDatasetSummary) -> pd.DataFrame | None:
    """Read the active current-relationship frame or show a database error."""

    try:
        return load_current_relationships(
            str(summary.dataset_id),
            dataset_version(summary),
            summary.current_relationship_count,
        )
    except Exception as exc:
        show_db_failure("read the current relationships", exc)
        return None


def scoring_model_for(summary: ActiveDatasetSummary) -> ScoringModel | None:
    """Return the cached final model fitted on the active current frame."""

    try:
        return load_scoring_model(
            str(summary.dataset_id),
            dataset_version(summary),
            summary.current_relationship_count,
        )
    except Exception as exc:
        show_db_failure("fit the churn model", exc)
        return None


def scores_for(summary: ActiveDatasetSummary, threshold: float) -> pd.DataFrame | None:
    """Score the active current relationships at one fixed threshold."""

    try:
        return load_scores(
            str(summary.dataset_id),
            dataset_version(summary),
            summary.current_relationship_count,
            threshold,
        )
    except Exception as exc:
        show_db_failure("score the current relationships", exc)
        return None


def configured_admin_password(settings: Settings) -> str | None:
    """Resolve the admin password from Streamlit secrets, then settings."""

    try:
        secret = st.secrets.get("admin_password")
    except Exception:
        secret = None
    if isinstance(secret, str) and secret.strip():
        return secret

    if settings.admin_password is not None:
        value = settings.admin_password.get_secret_value()
        if value.strip():
            return value
    return None


@st.cache_resource(show_spinner=False)
def ensure_admin_seed() -> AccountInfo | None:
    """Create or update the seeded administrator once per process.

    Returns None when no admin password is configured. A database failure
    raises, so Streamlit does not cache it and the next run retries.
    """

    settings = get_settings()
    password = configured_admin_password(settings)
    if password is None:
        return None

    with session_scope() as session:
        return ensure_admin_account(
            session,
            username=settings.admin_username,
            email=settings.admin_email,
            display_name=settings.admin_display_name,
            password=password,
        )


def seed_admin_account() -> None:
    """Run the admin seed at startup and keep the app usable on failure."""

    try:
        ensure_admin_seed()
    except Exception as exc:
        logger.warning("Admin seed unavailable: %s", exc)


_LIGHT_VARS = """
    --cl-bg: #FFFFFF;
    --cl-bg-soft: #F8FAFC;
    --cl-surface: #FFFFFF;
    --cl-surface-2: #F1F5F9;
    --cl-text: #0F172A;
    --cl-muted: #475569;
    --cl-border: #E2E8F0;
    --cl-primary: #0F766E;
    --cl-primary-soft: #CCFBF1;
    --cl-shadow: 0 1px 2px rgba(15, 23, 42, 0.06);
"""

_DARK_VARS = """
    --cl-bg: #0B1220;
    --cl-bg-soft: #0F1A2B;
    --cl-surface: #152238;
    --cl-surface-2: #111C2E;
    --cl-text: #E6EDF7;
    --cl-muted: #94A3B8;
    --cl-border: #24344D;
    --cl-primary: #2DD4BF;
    --cl-primary-soft: #134E4A;
    --cl-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
"""


def _theme_css(theme: str) -> str:
    normalized = theme.strip().lower()
    text_force = ""
    if normalized == "dark":
        variables = f":root {{{_DARK_VARS}}}"
        text_force = "p, span, label, li, dd, dt, td, th { color: var(--cl-text) !important; }"
    elif normalized == "light":
        variables = f":root {{{_LIGHT_VARS}}}"
        text_force = "p, span, label, li, dd, dt, td, th { color: var(--cl-text) !important; }"
    else:
        variables = (
            f":root {{{_LIGHT_VARS}}}@media (prefers-color-scheme: dark) {{:root {{{_DARK_VARS}}}}}"
        )

    return f"""
    <style>
    {variables}
    html, body, .stApp, [data-testid="stAppViewContainer"] {{
        background-color: var(--cl-bg) !important;
        color: var(--cl-text) !important;
    }}
    [data-testid="stHeader"], [data-testid="stToolbar"] {{ background: transparent !important; }}
    [data-testid="stDecoration"] {{
        background-image: linear-gradient(90deg, var(--cl-primary), #38BDF8) !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: var(--cl-surface-2) !important;
        border-right: 1px solid var(--cl-border);
    }}
    [data-testid="stSidebar"] * {{ color: var(--cl-text); }}
    h1, h2, h3, h4, h5, h6 {{ color: var(--cl-text) !important; letter-spacing: -0.015em; }}
    {text_force}
    [data-testid="stCaptionContainer"], .stCaption {{ color: var(--cl-muted) !important; }}
    hr {{ border-color: var(--cl-border) !important; }}
    [data-testid="stMetric"] {{
        background: var(--cl-surface);
        border: 1px solid var(--cl-border);
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: var(--cl-shadow);
    }}
    [data-testid="stMetricLabel"] p {{
        color: var(--cl-muted) !important;
        font-size: 0.8rem;
        letter-spacing: 0.02em;
    }}
    [data-testid="stMetricValue"] {{ color: var(--cl-text) !important; }}
    [data-testid="stExpander"] details {{
        background: var(--cl-surface);
        border: 1px solid var(--cl-border);
        border-radius: 12px;
    }}
    [data-testid="stExpander"] summary {{ color: var(--cl-text); }}
    [data-testid="stVerticalBlockBorderWrapper"] {{
        border-color: var(--cl-border) !important;
        border-radius: 16px;
    }}
    [data-baseweb="select"] > div,
    [data-baseweb="input"] > div,
    [data-baseweb="textarea"] > div {{
        background-color: var(--cl-surface) !important;
        border-color: var(--cl-border) !important;
        color: var(--cl-text) !important;
    }}
    input, textarea {{
        color: var(--cl-text) !important;
        background-color: transparent !important;
    }}
    [data-baseweb="popover"], [data-baseweb="menu"], [role="listbox"] {{
        background-color: var(--cl-surface) !important;
    }}
    li[role="option"] {{ color: var(--cl-text) !important; }}
    [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 1px solid var(--cl-border); }}
    [data-baseweb="tab"] {{ color: var(--cl-muted); }}
    [data-baseweb="tab"][aria-selected="true"] {{ color: var(--cl-primary); }}
    [data-testid="stDataFrame"] {{
        --gdg-accent-color: var(--cl-primary);
        --gdg-accent-light: var(--cl-primary-soft);
        --gdg-bg-bubble: var(--cl-surface);
        --gdg-bg-cell: var(--cl-surface);
        --gdg-bg-header: var(--cl-surface-2);
        --gdg-bg-header-has-focus: var(--cl-surface-2);
        --gdg-border-color: var(--cl-border);
        --gdg-link-color: var(--cl-primary);
        --gdg-text-dark: var(--cl-text);
        --gdg-text-group-header: var(--cl-text);
        --gdg-text-light: var(--cl-muted);
        --gdg-text-medium: var(--cl-text);
        border: 1px solid var(--cl-border);
        border-radius: 12px;
        overflow: hidden;
    }}
    [data-testid="stForm"] {{
        background: var(--cl-surface);
        border: 1px solid var(--cl-border);
        border-radius: 16px;
        padding: 1rem 1.25rem;
    }}
    .stButton > button, .stDownloadButton > button {{
        border-radius: 10px;
        border-color: var(--cl-border);
        color: var(--cl-text);
    }}
    [data-testid="stBaseButton-primary"] {{
        background-color: var(--cl-primary) !important;
        border-color: var(--cl-primary) !important;
        color: #05201C !important;
        font-weight: 600;
    }}
    [data-testid="stBaseButton-secondary"] {{
        background-color: var(--cl-surface) !important;
        border-color: var(--cl-border) !important;
        color: var(--cl-text) !important;
    }}
    [data-testid="stCodeBlock"] pre, pre, code {{
        background-color: var(--cl-surface-2) !important;
        color: var(--cl-text) !important;
        border-radius: 8px;
    }}
    [data-testid="stAlert"] {{ border-radius: 12px; }}
    .block-container {{
        padding-top: 2.4rem;
        padding-bottom: 3.5rem;
        max-width: 1180px;
    }}
    .cl-hero {{
        border-bottom: 1px solid var(--cl-border);
        padding-bottom: 1.1rem;
        margin-bottom: 1.4rem;
    }}
    .cl-eyebrow {{
        color: var(--cl-primary);
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.14em;
        text-transform: uppercase;
        margin-bottom: 0.35rem;
    }}
    .cl-hero h1 {{
        font-size: 2.1rem;
        line-height: 1.15;
        margin: 0 0 0.35rem 0;
    }}
    .cl-hero p {{
        color: var(--cl-muted) !important;
        font-size: 0.98rem;
        margin: 0;
    }}
    .cl-chip {{
        display: inline-block;
        background: var(--cl-primary-soft);
        color: var(--cl-primary) !important;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 600;
        letter-spacing: 0.04em;
        padding: 0.22rem 0.6rem;
        margin-right: 0.35rem;
    }}
    .cl-hero-meta {{
        color: var(--cl-muted);
        font-size: 0.82rem;
        margin-top: 0.75rem;
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 0.35rem;
    }}
    .cl-brand {{
        display: flex;
        align-items: center;
        gap: 0.65rem;
        padding: 0.2rem 0 0.9rem 0;
    }}
    .cl-brand-mark {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2.1rem;
        height: 2.1rem;
        border-radius: 11px;
        background: linear-gradient(135deg, var(--cl-primary), #38BDF8);
        color: #05201C !important;
        font-size: 0.78rem;
        font-weight: 800;
        letter-spacing: 0.02em;
    }}
    .cl-brand strong {{ font-size: 1.02rem; letter-spacing: -0.01em; }}
    .cl-brand-sub {{ color: var(--cl-muted) !important; font-size: 0.74rem; }}
    .cl-section {{
        margin: 1.9rem 0 0.7rem 0;
        padding-bottom: 0.35rem;
        border-bottom: 1px solid var(--cl-border);
    }}
    .cl-section h3 {{
        font-size: 1.05rem;
        margin: 0;
    }}
    .cl-section p {{
        color: var(--cl-muted) !important;
        font-size: 0.84rem;
        margin: 0.2rem 0 0 0;
    }}
    .cl-visitor {{
        background: var(--cl-surface);
        border: 1px solid var(--cl-border);
        border-radius: 14px;
        box-shadow: var(--cl-shadow);
        padding: 0.7rem 1rem 0.8rem 1rem;
        margin-bottom: 0.6rem;
    }}
    .cl-visitor .cl-eyebrow {{ margin-bottom: 0.45rem; }}
    .cl-visitor-grid {{
        display: flex;
        flex-wrap: wrap;
        gap: 1.8rem;
    }}
    .cl-visitor-grid div {{
        display: flex;
        flex-direction: column;
        line-height: 1.15;
    }}
    .cl-visitor-grid strong {{
        font-size: 1.25rem;
        color: var(--cl-text);
    }}
    .cl-visitor-grid span {{
        font-size: 0.74rem;
        color: var(--cl-muted) !important;
        letter-spacing: 0.02em;
    }}
    [data-testid="stImage"] img {{
        border: 1px solid var(--cl-border);
        border-radius: 12px;
        background: var(--cl-surface);
    }}
    </style>
    """


THEME_OPTIONS = ["Light", "Dark", "System"]


def render_theme() -> None:
    """Apply the selected palette. Call once per run, before navigation."""

    if st.session_state.get("ui_theme") not in THEME_OPTIONS:
        st.session_state["ui_theme"] = "System"
    st.markdown(_theme_css(st.session_state["ui_theme"]), unsafe_allow_html=True)


def render_appearance_control() -> None:
    """Render the sidebar appearance control. Call once per run."""

    st.sidebar.divider()
    st.sidebar.caption("Appearance")
    selected = st.sidebar.segmented_control(
        "Appearance",
        options=THEME_OPTIONS,
        key="ui_theme",
        required=True,
        label_visibility="collapsed",
        help="Light or dark palette. System follows your device setting.",
    )
    if selected is None:
        st.session_state["ui_theme"] = "System"
        st.rerun()


def render_sidebar() -> None:
    st.sidebar.markdown(
        '<div class="cl-brand">'
        '<span class="cl-brand-mark">CL</span>'
        "<span><strong>ChurnLab</strong><br>"
        '<span class="cl-brand-sub">Telecom churn analysis</span></span>'
        "</div>",
        unsafe_allow_html=True,
    )

    try:
        summary = load_active_summary()
    except Exception as exc:
        summary = None
        logger.warning("Sidebar summary unavailable: %s", exc)
        st.sidebar.error("Database unavailable")

    if summary is None:
        st.sidebar.caption("No active dataset")
    else:
        st.sidebar.caption(f"Active: **{summary.dataset_name}**")
        st.sidebar.caption(
            f"Snapshot {summary.as_of_date:%d %b %Y} · "
            f"{summary.current_relationship_count:,} current relationships"
        )

    try:
        connection = load_connection_status()
    except Exception as exc:
        logger.warning("Sidebar connection check failed: %s", exc)
        st.sidebar.caption("Database status unavailable")
    else:
        version_short = " ".join(connection.server_version.split()[:2])
        st.sidebar.caption(
            f"Neon {version_short} · {connection.database} · {connection.latency_ms:.0f} ms"
        )

    if st.sidebar.button("Refresh data", width="stretch"):
        clear_caches()
        st.rerun()

    st.sidebar.divider()
    account = current_account()
    if account is not None:
        if account.is_admin:
            st.sidebar.success(f"Administrator: {account.display_name}")
        else:
            st.sidebar.success(f"Signed in as {account.display_name}")
        if st.sidebar.button("Sign out", width="stretch", key="account-signout"):
            sign_out_session()
            st.rerun()
    else:
        st.sidebar.caption("Account: signed out")

    st.sidebar.divider()
    if account is not None and account.is_admin:
        st.sidebar.success("Admin tools: unlocked")
    elif st.session_state.get("admin_authenticated"):
        st.sidebar.success("Admin: signed in")
        if st.sidebar.button("Sign out of admin", width="stretch", key="admin-signout"):
            st.session_state.pop("admin_authenticated", None)
            st.rerun()
    else:
        st.sidebar.caption("Admin: locked")

    st.sidebar.divider()
    st.sidebar.caption(
        "Relationship churn covers all history. Current customer churn covers "
        "only the latest relationship per customer."
    )
    render_appearance_control()


def hero(
    title: str,
    subtitle: str,
    *,
    eyebrow: str = "ChurnLab",
    chips: tuple[str, ...] = (),
    meta: str = "",
) -> None:
    """Render a page hero with an optional chip row and meta line."""

    chip_html = "".join(f'<span class="cl-chip">{html.escape(chip)}</span>' for chip in chips)
    meta_html = ""
    if chip_html or meta:
        meta_html = f'<div class="cl-hero-meta">{chip_html}{meta}</div>'

    st.markdown(
        f'<div class="cl-hero">'
        f'<div class="cl-eyebrow">{html.escape(eyebrow)}</div>'
        f"<h1>{html.escape(title)}</h1>"
        f"<p>{html.escape(subtitle)}</p>"
        f"{meta_html}"
        f"</div>",
        unsafe_allow_html=True,
    )


def page_header(
    title: str,
    subtitle: str,
    summary: ActiveDatasetSummary | None,
    *,
    eyebrow: str = "ChurnLab",
    chips: tuple[str, ...] = (),
) -> None:
    """Render the page hero and the active dataset context."""

    if summary is not None:
        meta = (
            f"Active dataset <strong>{html.escape(summary.dataset_name)}</strong>"
            f" · snapshot {summary.as_of_date:%d %b %Y}"
            f" · {summary.current_relationship_count:,} current relationships"
        )
    else:
        meta = "No active dataset"

    hero(title, subtitle, eyebrow=eyebrow, chips=chips, meta=meta)


def render_empty_dataset() -> None:
    st.info(
        "No active dataset. Activate a dataset on the Admin page in the sidebar "
        "before using analytics or scoring."
    )


def render_profile(summary: ActiveDatasetSummary) -> None:
    if summary.min_registration_date and summary.max_registration_date:
        window = (
            f"{summary.min_registration_date:%d %b %Y} to {summary.max_registration_date:%d %b %Y}"
        )
    else:
        window = "registration window unavailable"

    st.markdown(f"**{summary.dataset_name}** · snapshot {summary.as_of_date:%d %b %Y} · {window}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Relationships — all history", f"{summary.relationship_count:,}")
    col2.metric("Unique customers", f"{summary.unique_customers:,}")
    col3.metric(
        "Relationship churn — all history",
        f"{summary.relationship_churn_count:,} ({summary.relationship_churn_rate:.2f}%)",
    )
    col4.metric(
        "Current customer churn — latest only",
        f"{summary.current_churn_count:,} ({summary.current_churn_rate:.2f}%)",
    )

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Multi-provider customers", f"{summary.multi_relationship_customers:,}")
    col6.metric("Current relationships", f"{summary.current_relationship_count:,}")
    col7.metric("Telecom partners", f"{summary.partner_count:,}")
    col8.metric("Re-entry pairs", f"{summary.reentry_pairs:,}")

    st.caption(
        "One row is one customer-provider relationship. A customer can have multiple "
        "relationships over time; churn is provider-specific. Relationship churn and "
        "current customer churn are different measures and must not be combined."
    )

    profile_rows: list[dict[str, str | int]] = [
        {
            "Profile": f"Customers with {count} relationship(s)",
            "Value": frequency,
        }
        for count, frequency in sorted(
            summary.relationship_count_distribution.items(),
            key=lambda item: int(item[0]),
        )
    ]
    profile_rows.extend(
        [
            {
                "Profile": "Historical (non-latest) relationships",
                "Value": summary.historical_relationships,
            },
            {
                "Profile": "Historical relationships churned",
                "Value": summary.historical_churned,
            },
            {
                "Profile": "Current (latest) relationships",
                "Value": summary.current_relationship_count,
            },
            {
                "Profile": "Current relationships churned",
                "Value": summary.current_churn_count,
            },
            {
                "Profile": "Re-entry customer-provider pairs",
                "Value": summary.reentry_pairs,
            },
        ]
    )
    st.dataframe(
        pd.DataFrame(profile_rows),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "All non-latest relationships are churned by dataset construction. "
        "A returning customer-provider pair is a legitimate relationship, not a duplicate."
    )


def render_issue_table(report: ValidationReport) -> None:
    if report.errors:
        st.error(
            f"{report.error_count} validation error(s) found. Nothing will be "
            "written until the file is fixed."
        )
        error_frame = pd.DataFrame(
            [
                {
                    "Row": issue.row_number,
                    "Code": issue.code,
                    "Column": issue.column,
                    "Value": issue.value,
                    "Message": issue.message,
                }
                for issue in report.errors
            ]
        )
        st.dataframe(error_frame, hide_index=True, width="stretch")
        if report.errors_truncated:
            st.caption(f"Showing the first {len(report.errors)} of {report.error_count} errors.")

    if report.warnings:
        st.warning(f"{report.warning_count} validation warning(s).")
        warning_frame = pd.DataFrame(
            [
                {
                    "Row": issue.row_number,
                    "Code": issue.code,
                    "Column": issue.column,
                    "Value": issue.value,
                    "Message": issue.message,
                }
                for issue in report.warnings
            ]
        )
        st.dataframe(warning_frame, hide_index=True, width="stretch")
        if report.warnings_truncated:
            st.caption(
                f"Showing the first {len(report.warnings)} of {report.warning_count} warnings."
            )


def render_validation(report: ValidationReport, cleaned: pd.DataFrame) -> None:
    if report.has_errors:
        render_issue_table(report)
    else:
        st.success("Validation passed. The file is ready to load.")
        if report.warnings:
            render_issue_table(report)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Relationships", f"{report.row_count:,}")
    col2.metric("Unique customers", f"{report.unique_customers:,}")
    col3.metric(
        "Relationship churn",
        f"{report.relationship_churn_count:,} ({report.relationship_churn_rate:.2f}%)",
    )
    col4.metric(
        "Current churn",
        f"{report.current_churn_count:,} ({report.current_churn_rate:.2f}%)",
    )

    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Multi-provider customers", f"{report.multi_relationship_customers:,}")
    col6.metric("Re-entry pairs", f"{report.reentry_pairs:,}")
    col7.metric(
        "Snapshot date",
        report.as_of_date.strftime("%d %b %Y") if report.as_of_date else "—",
    )
    col8.metric("Historical relationships", f"{report.historical_relationships:,}")

    if report.date_min and report.date_max:
        st.caption(f"Registration dates: {report.date_min:%d %b %Y} to {report.date_max:%d %b %Y}.")

    st.markdown("**Preview — first 20 cleaned rows**")
    st.dataframe(cleaned.head(20), hide_index=True, width="stretch")


def format_proportion(value: float) -> str:
    return f"{value * 100:.2f}%"


def format_percentage(value: float) -> str:
    return f"{value:.2f}%"


def section_header(title: str, description: str = "") -> None:
    """Render a consistent section heading."""

    detail = f"<p>{html.escape(description)}</p>" if description else ""
    st.markdown(
        f'<div class="cl-section"><h3>{html.escape(title)}</h3>{detail}</div>',
        unsafe_allow_html=True,
    )


def render_notebook_charts(section: str, chart_filenames: list[str], captions: list[str]) -> None:
    """Render notebook charts as a two-column grid inside an expander."""
    if not chart_filenames:
        return

    section_header(
        f"Notebook evidence — {section}",
        "Static figures from the analysis notebook. Open the panel to review them.",
    )
    expander_title = f"Show {len(chart_filenames)} charts"
    root = Path(__file__).resolve().parent / "assets"
    with st.expander(expander_title, expanded=False):
        cols = st.columns(2)
        for i, (fname, caption) in enumerate(zip(chart_filenames, captions, strict=False)):
            with cols[i % 2]:
                st.image(
                    str(root / fname),
                    caption=f"{i + 1}. {caption}",
                    width="stretch",
                )


def threshold_badge(policy: ThresholdPolicy) -> None:
    st.markdown(f"**{policy.label}** · threshold `{policy.threshold:.4f}`")
    st.caption(policy.note)


def render_rate_table(
    table: pd.DataFrame,
    *,
    segment_label: str = "Segment",
    caption: str | None = None,
) -> None:
    display = pd.DataFrame(
        {
            segment_label: table["segment"],
            "N": table["n"],
            "Churned": table["churned"],
            "Rate %": (table["rate"] * 100).round(2),
            "95% CI low %": (table["ci_low"] * 100).round(2),
            "95% CI high %": (table["ci_high"] * 100).round(2),
            "Share %": (table["share"] * 100).round(2),
            "Small sample": table["small_sample"].map({True: "yes", False: ""}),
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Rate %": st.column_config.NumberColumn(format="%.2f"),
            "95% CI low %": st.column_config.NumberColumn(format="%.2f"),
            "95% CI high %": st.column_config.NumberColumn(format="%.2f"),
            "Share %": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    if caption:
        st.caption(caption)


def render_rate_bar(
    table: pd.DataFrame,
    *,
    title: str | None = None,
    height: int = 320,
) -> None:
    if title:
        st.markdown(f"**{title}**")
    chart = table.set_index("segment")[["rate"]].mul(100).rename(columns={"rate": "Rate %"})
    st.bar_chart(chart, height=height)


def render_current_filters(
    frame: pd.DataFrame,
    *,
    key_prefix: str,
    include_providers: bool = True,
    include_genders: bool = True,
    include_states: bool = False,
    include_age: bool = False,
    include_tenure: bool = False,
) -> pd.DataFrame:
    """Render a filter panel and return the filtered current-relationship frame."""

    providers: list[str] | None = None
    genders: list[str] | None = None
    states: list[str] | None = None
    age_range: tuple[int, int] | None = None
    tenure_range: tuple[int, int] | None = None

    with st.expander("Filters", expanded=False):
        left, right = st.columns(2)
        with left:
            if include_providers:
                provider_options = sorted(frame["telecom_partner"].dropna().unique().tolist())
                providers = (
                    st.multiselect(
                        "Telecom provider",
                        options=provider_options,
                        key=f"{key_prefix}-providers",
                        placeholder="All providers",
                    )
                    or None
                )
            if include_states:
                state_options = sorted(frame["state"].dropna().unique().tolist())
                states = (
                    st.multiselect(
                        "State",
                        options=state_options,
                        key=f"{key_prefix}-states",
                        placeholder="All states",
                    )
                    or None
                )
            if include_tenure:
                tenure_min = int(frame["tenure_days"].min())
                tenure_max = int(frame["tenure_days"].max())
                if tenure_min < tenure_max:
                    tenure_range = st.slider(
                        "Tenure range (days)",
                        min_value=tenure_min,
                        max_value=tenure_max,
                        value=(tenure_min, tenure_max),
                        key=f"{key_prefix}-tenure",
                    )
                else:
                    st.caption(f"Tenure: {tenure_min:,} days for all filtered rows.")
        with right:
            if include_genders:
                gender_options = sorted(frame["gender"].dropna().unique().tolist())
                genders = (
                    st.multiselect(
                        "Gender",
                        options=gender_options,
                        key=f"{key_prefix}-genders",
                        placeholder="All genders",
                    )
                    or None
                )
            if include_age:
                age_min = int(frame["age"].min())
                age_max = int(frame["age"].max())
                if age_min < age_max:
                    age_range = st.slider(
                        "Age range",
                        min_value=age_min,
                        max_value=age_max,
                        value=(age_min, age_max),
                        key=f"{key_prefix}-age",
                    )
                else:
                    st.caption(f"Age: {age_min} years for all filtered rows.")

    return filter_current_frame(
        frame,
        providers=providers,
        states=states,
        genders=genders,
        age_range=age_range,
        tenure_range=tenure_range,
    )


def render_usage_table(
    table: pd.DataFrame,
    *,
    metric_label: str,
    caption: str | None = None,
) -> None:
    display = pd.DataFrame(
        {
            "Quartile": table["segment"],
            f"{metric_label} min": table["min_value"].round(2),
            f"{metric_label} max": table["max_value"].round(2),
            "N": table["n"],
            "Churned": table["churned"],
            "Rate %": (table["rate"] * 100).round(2),
            "95% CI low %": (table["ci_low"] * 100).round(2),
            "95% CI high %": (table["ci_high"] * 100).round(2),
        }
    )
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={
            "Rate %": st.column_config.NumberColumn(format="%.2f"),
            "95% CI low %": st.column_config.NumberColumn(format="%.2f"),
            "95% CI high %": st.column_config.NumberColumn(format="%.2f"),
        },
    )
    if caption:
        st.caption(caption)
