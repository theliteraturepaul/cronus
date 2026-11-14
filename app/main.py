"""Cronus Streamlit entrypoint: connection status, upload, and datasets."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

import pandas as pd
import streamlit as st

from cronus.config import Settings, get_settings
from cronus.db import check_connection, session_scope
from cronus.ingest import ingest_dataframe
from cronus.logging import configure_logging
from cronus.repository import (
    activate_dataset,
    get_active_dataset_summary,
    get_dataset_by_hash,
    list_datasets,
)
from cronus.schemas import (
    ActiveDatasetSummary,
    DatasetAlreadyExists,
    DatasetInfo,
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


@st.cache_data(ttl=60, show_spinner=False)
def load_active_summary() -> ActiveDatasetSummary | None:
    with session_scope() as session:
        return get_active_dataset_summary(session)


@st.cache_data(ttl=60, show_spinner=False)
def load_datasets() -> list[DatasetInfo]:
    with session_scope() as session:
        return list_datasets(session)


def _show_flash() -> None:
    message = st.session_state.pop("flash_success", None)
    if message:
        st.success(message)


def _show_db_failure(action: str, exc: Exception) -> None:
    logger.exception("Database operation failed: %s", action, exc_info=exc)
    st.error(
        f"Could not {action}. The Neon database may be waking up, or the "
        "connection details in .env may be wrong. No credentials were displayed."
    )


def _render_db_status() -> None:
    try:
        info = check_connection()
    except Exception as exc:
        _show_db_failure("connect to Neon", exc)
        with st.expander("Troubleshooting", expanded=True):
            st.markdown(
                "- Confirm `.env` exists in the repository root.\n"
                "- `DATABASE_URL` must be the pooled Neon URL (host contains `-pooler`).\n"
                "- `DIRECT_URL` must be the direct URL used only by Alembic.\n"
                "- A new Neon compute may need a few seconds to wake up."
            )
        st.stop()

    version_short = " ".join(info.server_version.split()[:2])
    column_a, column_b, column_c = st.columns(3)
    column_a.metric("Neon server", version_short)
    column_b.metric("Database", info.database)
    column_c.metric("Latency", f"{info.latency_ms:.0f} ms")
    st.caption("Pooled connection · credentials are never displayed.")


def _render_profile(summary: ActiveDatasetSummary) -> None:
    if summary.min_registration_date and summary.max_registration_date:
        window = (
            f"{summary.min_registration_date:%d %b %Y} to {summary.max_registration_date:%d %b %Y}"
        )
    else:
        window = "registration window unavailable"

    st.markdown(f"**{summary.dataset_name}** · snapshot {summary.as_of_date:%d %b %Y} · {window}")

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Relationships", f"{summary.relationship_count:,}")
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
        "current-base churn are different measures and must not be combined."
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


def _render_active_dataset() -> None:
    st.subheader("Active dataset")
    try:
        summary = load_active_summary()
    except Exception as exc:
        _show_db_failure("read the active dataset", exc)
        return

    if summary is None:
        st.info(
            "No active dataset yet. Upload `Dataset/project_dataset.csv` below "
            "to load the baseline snapshot."
        )
        return

    _render_profile(summary)


def _render_issue_table(report: ValidationReport) -> None:
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


def _render_validation(report: ValidationReport, cleaned: pd.DataFrame) -> None:
    if report.has_errors:
        _render_issue_table(report)
    else:
        st.success("Validation passed. The file is ready to load.")
        if report.warnings:
            _render_issue_table(report)

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


def _load_existing(digest: str) -> DatasetLookup | None:
    try:
        with session_scope() as session:
            return get_dataset_by_hash(session, digest)
    except Exception as exc:
        _show_db_failure("check the file hash", exc)
        return None


def _success(message: str) -> None:
    st.cache_data.clear()
    st.session_state["flash_success"] = message
    st.rerun()


def _activate_existing(existing: DatasetLookup) -> None:
    try:
        with session_scope() as session:
            activate_dataset(session, existing.id)
    except Exception as exc:
        _show_db_failure("activate the dataset", exc)
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
            "Use the existing dataset panel above."
        )
        return
    except Exception as exc:
        _show_db_failure("load the dataset", exc)
        return

    _success(
        f"Loaded {result.row_count:,} relationships as {result.dataset_name!r} "
        f"in {result.elapsed_seconds:.1f}s."
    )


def _render_upload_panel(settings: Settings) -> None:
    st.divider()
    st.subheader("Upload a dataset")
    st.caption(
        "Local-only upload in Phase 1. Phase 4 adds an admin-password gate before "
        "this panel is exposed in deployment."
    )

    uploaded = st.file_uploader("Upload churn CSV", type=["csv"])
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
            "The file could not be validated. Check that it is a UTF-8 CSV with the "
            "expected 14 columns."
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
            key=f"activate-existing-{digest[:12]}",
            disabled=existing.is_active,
        ):
            _activate_existing(existing)

        replace_name = st.text_input(
            "Dataset name for replacement",
            value=existing.name,
            key=f"replace-name-{digest[:12]}",
        )
        activate_after = st.checkbox(
            "Activate after load",
            value=True,
            key=f"replace-activate-{digest[:12]}",
        )
        confirm_replace = st.checkbox(
            "I understand this deletes the existing dataset with the same hash "
            "and reloads it from this file.",
            key=f"replace-confirm-{digest[:12]}",
        )
        replace_disabled = report.has_errors or not confirm_replace or not replace_name.strip()
        if st.button(
            "Replace with this file",
            type="primary",
            key=f"replace-{digest[:12]}",
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
            key=f"dataset-name-{digest[:12]}",
        )
        activate_after = st.checkbox(
            "Activate after load",
            value=True,
            key=f"activate-after-{digest[:12]}",
        )
        load_disabled = report.has_errors or not dataset_name.strip()
        if st.button(
            "Load dataset",
            type="primary",
            key=f"load-{digest[:12]}",
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

    _render_validation(report, cleaned)


def _render_datasets() -> None:
    st.divider()
    st.subheader("Datasets")
    try:
        datasets = load_datasets()
    except Exception as exc:
        _show_db_failure("list datasets", exc)
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

    labels = {
        f"{dataset.name} · uploaded {dataset.uploaded_at:%Y-%m-%d %H:%M}": dataset
        for dataset in datasets
    }
    selected_label = st.selectbox("Select a dataset", list(labels))
    selected = labels[selected_label]
    if selected.is_active:
        st.caption("This dataset is already active.")
    if st.button("Activate selected dataset", disabled=selected.is_active):
        _activate_existing(
            DatasetLookup(
                id=selected.id,
                name=selected.name,
                relationship_count=selected.relationship_count,
                is_active=selected.is_active,
            )
        )


def main() -> None:
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

    st.title("Cronus — Telecom Churn Intelligence")
    st.caption("Customer-provider relationship analytics · Data Analytics with Python and Power BI")
    _show_flash()
    _render_db_status()

    _render_active_dataset()
    if st.button("Refresh data"):
        st.cache_data.clear()
        st.rerun()

    _render_upload_panel(settings)
    _render_datasets()

    st.divider()
    st.caption(
        "One row is one customer-provider relationship. Relationship churn covers all "
        "history; current churn covers only each customer's latest relationship. "
        "Never treat 19.87% as the current customer churn rate."
    )


main()
