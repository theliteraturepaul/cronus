"""Admin page: dataset activation for administrators only."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    clear_caches,
    current_account,
    load_datasets,
    page_header,
    render_profile,
    section_header,
    show_db_failure,
)

from cronus.db import session_scope
from cronus.repository import activate_dataset
from cronus.schemas import DatasetLookup


def _success(message: str) -> None:
    clear_caches()
    st.session_state["flash_success"] = message
    st.rerun()


def _activate_existing(existing: DatasetLookup) -> None:
    try:
        with session_scope() as session:
            activate_dataset(session, existing.id)
    except Exception as exc:
        show_db_failure("activate the dataset", exc)
        return
    _success(f"Activated dataset {existing.name!r}.")


def _render_datasets() -> None:
    section_header("Datasets", "Activate an existing dataset or inspect the load history.")
    try:
        datasets = load_datasets()
    except Exception as exc:
        show_db_failure("list datasets", exc)
        return

    if not datasets:
        st.info("No datasets have been uploaded yet.")
        return

    rows = [
        {
            "Name": dataset.name,
            "Relationships": dataset.relationship_count,
            "Customers": dataset.unique_customers,
            "Relationship churn %": dataset.relationship_churn_rate,
            "Current churn %": dataset.current_churn_rate,
            "Active": "yes" if dataset.is_active else "",
            "Uploaded": dataset.uploaded_at.strftime("%Y-%m-%d %H:%M"),
            "Hash": dataset.file_sha256_prefix,
        }
        for dataset in datasets
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(
        "Activation changes the dataset used by every page. Cached reads and "
        "the fitted model are cleared after a change."
    )

    labels = {
        f"{dataset.name} · uploaded {dataset.uploaded_at:%Y-%m-%d %H:%M}": dataset
        for dataset in datasets
    }
    selected_label = st.selectbox(
        "Select a dataset",
        list(labels),
        key="admin-dataset-select",
    )
    selected = labels[selected_label]
    if selected.is_active:
        st.caption("This dataset is already active.")
    if st.button(
        "Activate selected dataset",
        disabled=selected.is_active,
        key="admin-activate-selected",
    ):
        _activate_existing(
            DatasetLookup(
                id=selected.id,
                name=selected.name,
                relationship_count=selected.relationship_count,
                is_active=selected.is_active,
            )
        )


def render() -> None:
    summary, summary_ok = active_summary_state()
    page_header(
        "Admin",
        "Dataset replacement and activation for administrators only.",
        summary,
        eyebrow="Data operations",
        chips=("Admin-only access", "Dataset management"),
    )

    if not summary_ok:
        return

    account = current_account()
    if account is None or not account.is_admin:
        st.error(
            "This page is restricted to administrators. "
            "Use the Upload dataset button in the sidebar to stage a file. "
            "Only the seeded administrator account can replace or activate datasets."
        )
        return

    st.success(f"Admin tools unlocked by the administrator account {account.display_name!r}.")
    st.caption(
        "The seeded account passed its password check on the Account page. "
        "Sign-out is in the sidebar."
    )

    if summary is None:
        st.info(
            "No active dataset. Upload `Dataset/project_dataset.csv` from the "
            "Upload dataset page in the sidebar to load the baseline snapshot."
        )
    else:
        section_header(
            "Active dataset",
            "The current frame that powers analytics and scoring.",
        )
        render_profile(summary)

    st.divider()
    _render_datasets()

    st.divider()
    st.caption(
        "Admin actions write to the configured database. Validate the file "
        "before you activate or replace a dataset."
    )
