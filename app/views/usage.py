"""Usage and tenure page: descriptive churn patterns in the current frame."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    current_frame_for,
    page_header,
    render_current_filters,
    render_empty_dataset,
    render_rate_bar,
    render_rate_table,
    render_usage_table,
)

from cronus.analytics import (
    registration_cohort_table,
    spearman_correlation_table,
    tenure_band_table,
    usage_quartile_table,
)


def _render_usage_tab(
    frame: pd.DataFrame,
    column: str,
    label: str,
    caption: str,
) -> None:
    try:
        table = usage_quartile_table(frame, column)
    except ValueError as exc:
        st.info(f"The selected filters do not support {label.lower()} quartiles: {exc}")
        return
    render_usage_table(table, metric_label=label, caption=caption)
    render_rate_bar(table, title=f"Current churn rate by {label.lower()} quartile")


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Usage and tenure",
        "Current churn by tenure band, usage quartile, registration cohort, and rank correlation.",
        summary,
    )

    if not ok:
        return
    if summary is None:
        render_empty_dataset()
        return

    frame = current_frame_for(summary)
    if frame is None:
        return

    st.caption(
        "All comparisons use the latest relationship per customer. "
        "Historical relationships are excluded."
    )
    filtered = render_current_filters(
        frame,
        key_prefix="usage",
        include_providers=True,
        include_genders=False,
        include_states=False,
        include_age=True,
        include_tenure=True,
    )

    if filtered.empty:
        st.warning("No current relationships match the selected filters.")
        return

    total = len(filtered)
    churned = int(filtered["churn"].sum())
    col1, col2, col3 = st.columns(3)
    col1.metric("Current relationships", f"{total:,}")
    col2.metric("Churned — latest only", f"{churned:,}")
    col3.metric("Current churn rate", f"{(churned / total) * 100:.2f}%")

    tenure_tab, calls_tab, sms_tab, data_tab, cohort_tab, correlation_tab = st.tabs(
        [
            "Tenure",
            "Calls",
            "SMS",
            "Data",
            "Registration cohorts",
            "Correlations",
        ]
    )

    with tenure_tab:
        tenure_table = tenure_band_table(filtered)
        render_rate_table(
            tenure_table,
            segment_label="Tenure band",
            caption=(
                "Historical tenure uses the next registration date as a switch proxy. "
                "Latest-relationship tenure uses the snapshot date."
            ),
        )
        render_rate_bar(tenure_table, title="Current churn rate by tenure band")

    with calls_tab:
        _render_usage_tab(
            filtered,
            "calls_made",
            "Calls",
            ("Quartiles are computed on the filtered current frame. Q1 is the lowest usage group."),
        )

    with sms_tab:
        _render_usage_tab(
            filtered,
            "sms_sent",
            "SMS",
            ("Quartiles are computed on the filtered current frame. Q1 is the lowest usage group."),
        )

    with data_tab:
        _render_usage_tab(
            filtered,
            "data_used",
            "Data",
            ("Quartiles are computed on the filtered current frame. Q1 is the lowest usage group."),
        )

    with cohort_tab:
        cohort_table = registration_cohort_table(filtered)
        render_rate_table(
            cohort_table,
            segment_label="Registration year",
            caption=(
                "Cohorts use the registration year. Earlier cohorts have longer "
                "observation windows in this snapshot."
            ),
        )
        render_rate_bar(cohort_table, title="Current churn rate by registration year")

    with correlation_tab:
        correlation = spearman_correlation_table(filtered)
        display = pd.DataFrame(
            {
                "Feature": correlation["feature"],
                "Spearman rho": correlation["correlation"].round(4),
                "N": correlation["n"],
            }
        )
        st.dataframe(display, hide_index=True, width="stretch")
        st.bar_chart(
            correlation.set_index("feature")[["correlation"]].rename(
                columns={"correlation": "Spearman rho"}
            ),
            height=320,
        )
        st.caption(
            "Spearman rho measures rank association with current churn in the "
            "filtered frame. It is not a causal effect."
        )
