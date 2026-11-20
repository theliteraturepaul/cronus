"""ChurnLab Streamlit entrypoint and navigation shell."""

from __future__ import annotations

import streamlit as st
from shared import (
    current_account,
    render_guest_sidebar,
    render_sidebar,
    render_theme,
    render_visitor_banner,
    seed_admin_account,
    show_flash,
)
from views import account as account_view
from views import admin, overview, performance, powerbi, predictions, providers, upload, usage

from cronus.config import get_settings
from cronus.logging import configure_logging

st.set_page_config(
    page_title="ChurnLab — Telecom Customer Churn Intelligence/Analysis System",
    page_icon="📊",
    layout="wide",
)

try:
    settings = get_settings()
except Exception:
    st.error(
        "ChurnLab is not configured. Copy `.env.example` to `.env` and provide "
        "`DATABASE_URL` and `DIRECT_URL`. No credentials are displayed."
    )
    st.stop()

configure_logging(settings.log_level)
seed_admin_account()

render_theme()

account = current_account()
show_flash()
render_visitor_banner(account)

if account is None:
    render_guest_sidebar()
    guest_navigation = st.navigation(
        [
            st.Page(
                account_view.render,
                title="Sign in",
                icon=":material/login:",
                url_path="account",
                default=True,
            )
        ],
        position="hidden",
    )
    guest_navigation.run()
else:
    upload_page = st.Page(
        upload.render,
        title="Upload dataset",
        icon=":material/cloud_upload:",
        url_path="upload",
        visibility="hidden",
    )
    pages = [
        st.Page(
            overview.render,
            title="Overview",
            icon=":material/dashboard:",
            url_path="overview",
            default=True,
        ),
        st.Page(
            providers.render,
            title="Providers and segments",
            icon=":material/groups:",
            url_path="providers",
        ),
        st.Page(
            usage.render,
            title="Usage and tenure",
            icon=":material/query_stats:",
            url_path="usage",
        ),
        st.Page(
            performance.render,
            title="Model performance",
            icon=":material/monitoring:",
            url_path="performance",
        ),
        st.Page(
            predictions.render,
            title="Churn predictions",
            icon=":material/notification_important:",
            url_path="predictions",
        ),
        st.Page(
            powerbi.render,
            title="Power BI dashboard",
            icon=":material/bar_chart:",
            url_path="powerbi",
        ),
        st.Page(
            admin.render,
            title="Admin",
            icon=":material/admin_panel_settings:",
            url_path="admin",
        ),
        st.Page(
            account_view.render,
            title="Account",
            icon=":material/person:",
            url_path="account",
        ),
        upload_page,
    ]

    render_sidebar()
    if st.sidebar.button("Upload dataset", icon=":material/cloud_upload:", width="stretch"):
        st.switch_page(upload_page)
    navigation = st.navigation(pages, position="sidebar")
    navigation.run()
