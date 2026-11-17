"""Admin page: password gate, uploads, replacement, and dataset activation."""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    clear_caches,
    configured_admin_password,
    load_datasets,
    page_header,
    render_profile,
    render_validation,
    show_db_failure,
)

from cronus.auth import verify_admin_password
from cronus.config import Settings, get_settings
from cronus.db import session_scope
from cronus.ingest import ingest_dataframe
from cronus.repository import activate_dataset, get_dataset_by_hash
from cronus.schemas import (
    DatasetAlreadyExists,
    DatasetLookup,
    UploadLimitExceeded,
    ValidationReport,
)
from cronus.validation import (
    enforce_upload_limits,
    estimate_csv_data_rows,
    validate_csv,
)

logger = logging.getLogger("cronus.app")

MAX_ATTEMPTS = 5
LOCK_SECONDS = 60


def _render_login(expected: str) -> None:
    st.subheader("Admin sign-in")
    st.caption(
        "Upload, replacement, and activation stay locked until the session "
        "passes the password check."
    )

    lock_until = float(st.session_state.get("admin_lock_until", 0.0))
    remaining = lock_until - time.time()
    if remaining > 0:
        st.error(
            f"Too many failed attempts. Admin sign-in is locked for {remaining:.0f} more seconds."
        )
        return

    with st.form("admin-login", clear_on_submit=True):
        candidate = st.text_input(
            "Admin password",
            type="password",
            key="admin-password-input",
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if not submitted:
        return

    if verify_admin_password(candidate, expected):
        st.session_state["admin_authenticated"] = True
        st.session_state.pop("admin_failed_attempts", None)
        st.session_state.pop("admin_lock_until", None)
        st.rerun()

    attempts = int(st.session_state.get("admin_failed_attempts", 0)) + 1
    if attempts >= MAX_ATTEMPTS:
        st.session_state["admin_failed_attempts"] = 0
        st.session_state["admin_lock_until"] = time.time() + LOCK_SECONDS
        st.error(f"Too many failed attempts. Admin sign-in is locked for {LOCK_SECONDS} seconds.")
    else:
        st.session_state["admin_failed_attempts"] = attempts
        st.error(
            f"Sign-in failed. {MAX_ATTEMPTS - attempts} attempt(s) remain before a temporary lock."
        )


def _load_existing(digest: str) -> DatasetLookup | None:
    try:
        with session_scope() as session:
            return get_dataset_by_hash(session, digest)
    except Exception as exc:
        show_db_failure("check the file hash", exc)
        return None


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


def _load_new(
    *,
    cleaned: pd.DataFrame,
    report: ValidationReport,
    dataset_name: str,
    original_filename: str,
    digest: str,
    activate: bool,
    replace: bool,
) -> None:
    try:
        result = ingest_dataframe(
            cleaned,
            dataset_name=dataset_name,
            original_filename=original_filename,
            file_sha256=digest,
            as_of_date=report.as_of_date,
            activate=activate,
            replace=replace,
            validation_report=report,
        )
    except DatasetAlreadyExists as exc:
        st.warning(
            f"That file is already stored as {exc.dataset_name!r}. "
            "Use the existing dataset panel below."
        )
        return
    except Exception as exc:
        show_db_failure("load the dataset", exc)
        return

    _success(
        f"Loaded {result.row_count:,} relationships as {result.dataset_name!r} "
        f"in {result.elapsed_seconds:.1f}s."
    )


def _render_upload_panel(settings: Settings) -> None:
    st.subheader("Upload a dataset")
    st.caption(
        f"Validation runs before any write. Hard errors leave the database "
        f"unchanged. Limits: {settings.max_upload_mb} MB and "
        f"{settings.max_upload_rows:,} data rows."
    )

    uploaded = st.file_uploader(
        "Upload churn CSV",
        type=["csv"],
        key="admin-upload",
    )
    if uploaded is None:
        return

    data = uploaded.getvalue()
    try:
        enforce_upload_limits(
            size_bytes=len(data),
            row_count=estimate_csv_data_rows(data),
            max_upload_mb=settings.max_upload_mb,
            max_upload_rows=settings.max_upload_rows,
        )
    except UploadLimitExceeded as exc:
        st.error(str(exc))
        return

    digest = hashlib.sha256(data).hexdigest()
    existing = _load_existing(digest)

    try:
        report, cleaned = validate_csv(data)
    except Exception as exc:
        logger.exception("Unexpected validation failure", exc_info=exc)
        st.error(
            "The file could not be validated. Check that it is a UTF-8 CSV with "
            "the expected 14 columns."
        )
        return

    try:
        enforce_upload_limits(
            size_bytes=len(data),
            row_count=report.row_count,
            max_upload_mb=settings.max_upload_mb,
            max_upload_rows=settings.max_upload_rows,
        )
    except UploadLimitExceeded as exc:
        st.error(str(exc))
        return

    activate_after = True
    dataset_name = Path(uploaded.name).stem or "churn-dataset"

    if existing is not None:
        active_label = "active" if existing.is_active else "inactive"
        st.warning(
            f"This exact file is already loaded as **{existing.name}** "
            f"({existing.relationship_count:,} relationships, {active_label})."
        )
        if st.button(
            "Activate existing dataset",
            key=f"admin-activate-existing-{digest[:12]}",
            disabled=existing.is_active,
        ):
            _activate_existing(existing)

        replace_name = st.text_input(
            "Dataset name for replacement",
            value=existing.name,
            key=f"admin-replace-name-{digest[:12]}",
        )
        activate_after = st.checkbox(
            "Activate after load",
            value=True,
            key=f"admin-replace-activate-{digest[:12]}",
        )
        confirm_replace = st.checkbox(
            "I understand this deletes the existing dataset with the same hash "
            "and reloads it from this file.",
            key=f"admin-replace-confirm-{digest[:12]}",
        )
        replace_disabled = report.has_errors or not confirm_replace or not replace_name.strip()
        if st.button(
            "Replace with this file",
            type="primary",
            key=f"admin-replace-{digest[:12]}",
            disabled=replace_disabled,
        ):
            _load_new(
                cleaned=cleaned,
                report=report,
                dataset_name=replace_name,
                original_filename=uploaded.name,
                digest=digest,
                activate=activate_after,
                replace=True,
            )
    else:
        dataset_name = st.text_input(
            "Dataset name",
            value=dataset_name,
            key=f"admin-dataset-name-{digest[:12]}",
        )
        activate_after = st.checkbox(
            "Activate after load",
            value=True,
            key=f"admin-activate-after-{digest[:12]}",
        )
        load_disabled = report.has_errors or not dataset_name.strip()
        if st.button(
            "Load dataset",
            type="primary",
            key=f"admin-load-{digest[:12]}",
            disabled=load_disabled,
        ):
            _load_new(
                cleaned=cleaned,
                report=report,
                dataset_name=dataset_name,
                original_filename=uploaded.name,
                digest=digest,
                activate=activate_after,
                replace=False,
            )

    render_validation(report, cleaned)


def _render_datasets() -> None:
    st.subheader("Datasets")
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
    selected_label = st.selectbox("Select a dataset", list(labels), key="admin-dataset-select")
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
        "Dataset upload, replacement, and activation behind an admin gate.",
        summary,
    )

    if not summary_ok:
        return

    try:
        settings = get_settings()
    except Exception:
        st.error(
            "Cronus is not configured. Copy `.env.example` to `.env` and provide "
            "`DATABASE_URL` and `DIRECT_URL`. No credentials are displayed."
        )
        return

    expected = configured_admin_password(settings)
    if expected is None:
        st.error(
            "Admin access is locked because no admin password is configured. "
            "Set `ADMIN_PASSWORD` in `.env` or `admin_password` in "
            "`.streamlit/secrets.toml`. Upload, replacement, and activation "
            "stay disabled."
        )
        return

    if not st.session_state.get("admin_authenticated"):
        _render_login(expected)
        return

    st.success("Admin signed in for this browser session.")
    st.caption("The password is never displayed, logged, or exported. Sign-out is in the sidebar.")

    if summary is None:
        st.info(
            "No active dataset. Upload `Dataset/project_dataset.csv` below to "
            "load the baseline snapshot."
        )
    else:
        st.subheader("Active dataset")
        render_profile(summary)

    st.divider()
    _render_upload_panel(settings)

    st.divider()
    _render_datasets()

    st.divider()
    st.caption(
        "Admin actions write to the configured database. Validate the file "
        "before you activate or replace a dataset."
    )
