"""Cronus Streamlit entrypoint and navigation shell."""

from __future__ import annotations

import streamlit as st
from shared import render_sidebar, show_flash
from views import admin, overview, performance, predictions, providers, usage

from cronus.config import get_settings
from cronus.logging import configure_logging

st.set_page_config(
    page_title="Cronus — Telecom Churn Intelligence",
    page_icon="🛰️",
    layout="wide",
)

try:
    settings = get_settings()
except Exception:
    st.error(
        "Cronus is not configured. Copy `.env.example` to `.env` and provide "
        "`DATABASE_URL` and `DIRECT_URL`. No credentials are displayed."
    )
    st.stop()

configure_logging(settings.log_level)

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
        admin.render,
        title="Admin",
        icon=":material/admin_panel_settings:",
        url_path="admin",
    ),
]

navigation = st.navigation(pages, position="sidebar")
render_sidebar()
show_flash()
navigation.run()
