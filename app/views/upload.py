"""Upload page: dataset upload for signed-in users."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    clear_caches,
    current_account,
    page_header,
    render_validation,
    section_header,
    show_db_failure,
)

from cronus.config import Settings, get_settings
from cronus.db import session_scope
from cronus.ingest import ingest_dataframe
from cronus.repository import activate_dataset, get_dataset_by_hash
from cronus.schemas import (
    AccountInfo,
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


def _render_upload_panel(settings: Settings, account: AccountInfo, is_admin: bool) -> None:
    section_header(
        "Upload a dataset",
        "Every signed-in user can stage a file. Only an administrator can replace or activate one.",
    )
    st.caption(
        f"Validation runs before any write. Hard errors leave the database "
        f"unchanged. Limits: {settings.max_upload_mb} MB and "
        f"{settings.max_upload_rows:,} data rows."
    )

    uploaded = st.file_uploader(
        "Upload churn CSV",
        type=["csv"],
        key="upload-csv",
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
        if is_admin:
            if st.button(
                "Activate existing dataset",
                key=f"upload-activate-existing-{digest[:12]}",
                disabled=existing.is_active,
            ):
                _activate_existing(existing)

            replace_name = st.text_input(
                "Dataset name for replacement",
                value=existing.name,
                key=f"upload-replace-name-{digest[:12]}",
            )
            activate_after = st.checkbox(
                "Activate after load",
                value=True,
                key=f"upload-replace-activate-{digest[:12]}",
            )
            confirm_replace = st.checkbox(
                "I understand this deletes the existing dataset with the same hash "
                "and reloads it from this file.",
                key=f"upload-replace-confirm-{digest[:12]}",
            )
            replace_disabled = report.has_errors or not confirm_replace or not replace_name.strip()
            if st.button(
                "Replace with this file",
                type="primary",
                key=f"upload-replace-{digest[:12]}",
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
            st.caption("Replacement and activation require admin access.")
    else:
        dataset_name = st.text_input(
            "Dataset name",
            value=dataset_name,
            key=f"upload-dataset-name-{digest[:12]}",
        )
        activate_after = st.checkbox(
            "Activate after load",
            value=is_admin,
            key=f"upload-activate-after-{digest[:12]}",
            disabled=not is_admin,
        )
        load_disabled = report.has_errors or not dataset_name.strip()
        if st.button(
            "Load dataset",
            type="primary",
            key=f"upload-load-{digest[:12]}",
            disabled=load_disabled,
        ):
            _load_new(
                cleaned=cleaned,
                report=report,
                dataset_name=dataset_name,
                original_filename=uploaded.name,
                digest=digest,
                activate=activate_after if is_admin else False,
                replace=False,
            )

    render_validation(report, cleaned)


def render() -> None:
    summary, summary_ok = active_summary_state()
    page_header(
        "Upload dataset",
        "Stage a new CSV file. Replacement and activation require admin access.",
        summary,
        eyebrow="Data operations",
        chips=("Upload open to signed-in users", "Replace and activate are admin-only"),
    )

    if not summary_ok:
        return

    try:
        settings = get_settings()
    except Exception:
        st.error(
            "ChurnLab is not configured. Copy `.env.example` to `.env` and provide "
            "`DATABASE_URL` and `DIRECT_URL`. No credentials are displayed."
        )
        return

    account = current_account()
    if account is None:
        st.warning("Sign in to upload a dataset.")
        return

    is_admin_user = account.is_admin
    if is_admin_user:
        st.success("Admin tools unlocked.")
    else:
        st.info("Upload is available. Replacement and activation require admin access.")

    if summary is None:
        st.info(
            "No active dataset. Upload `Dataset/project_dataset.csv` below to "
            "load the baseline snapshot."
        )

    _render_upload_panel(settings, account=account, is_admin=is_admin_user)

    st.divider()
    st.caption(
        "Admin actions write to the configured database. Validate the file "
        "before you activate or replace a dataset."
    )
