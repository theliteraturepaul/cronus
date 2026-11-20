"""Provider and segment page: current churn by provider, gender, age, and state."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    current_frame_for,
    page_header,
    render_current_filters,
    render_empty_dataset,
    render_notebook_charts,
    render_rate_bar,
    render_rate_table,
    section_header,
)

from cronus.analytics import age_band_table, churn_rate_table, wilson_interval

SMALL_SAMPLE = 30


def _sort_by_rate(table: pd.DataFrame) -> pd.DataFrame:
    return table.sort_values(
        ["rate", "n", "segment"],
        ascending=[False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def _render_segment(
    table: pd.DataFrame,
    *,
    segment_label: str,
    chart_title: str,
    caption: str,
) -> None:
    ordered = _sort_by_rate(table)
    render_rate_table(ordered, segment_label=segment_label, caption=caption)
    render_rate_bar(ordered, title=chart_title)


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Providers and segments",
        "Current customer churn by provider, gender, age band, and state.",
        summary,
        chips=("Current frame", "Descriptive comparison"),
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
        key_prefix="segments",
        include_providers=True,
        include_genders=True,
        include_states=True,
        include_age=True,
    )

    if filtered.empty:
        st.warning("No current relationships match the selected filters.")
        return

    total = len(filtered)
    churned = int(filtered["churn"].sum())
    rate = churned / total
    low, high = wilson_interval(churned, total)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Current relationships", f"{total:,}")
    col2.metric("Churned — latest only", f"{churned:,}")
    col3.metric("Current churn rate", f"{rate * 100:.2f}%")
    col4.metric("95% Wilson interval", f"{low * 100:.2f}% – {high * 100:.2f}%")

    st.caption(
        f"Rate denominator: {total:,} filtered current relationships. "
        f"Small-sample segments have fewer than {SMALL_SAMPLE} relationships."
    )

    section_header(
        "Segment comparisons",
        "Tables show the count, rate, interval, and share for each segment.",
    )
    provider_tab, gender_tab, age_tab, state_tab = st.tabs(
        ["Providers", "Gender", "Age bands", "States"]
    )

    with provider_tab:
        provider_table = churn_rate_table(
            filtered,
            "telecom_partner",
            min_n=SMALL_SAMPLE,
        )
        _render_segment(
            provider_table,
            segment_label="Provider",
            chart_title="Current churn rate by provider",
            caption=(
                "Provider rates describe the filtered current snapshot. "
                "They do not identify causes of churn."
            ),
        )

    with gender_tab:
        gender_table = churn_rate_table(filtered, "gender", min_n=SMALL_SAMPLE)
        _render_segment(
            gender_table,
            segment_label="Gender",
            chart_title="Current churn rate by gender",
            caption=(
                "Gender is a recorded attribute in this snapshot. The comparison is descriptive."
            ),
        )

    with age_tab:
        age_table = age_band_table(filtered)
        _render_segment(
            age_table,
            segment_label="Age band",
            chart_title="Current churn rate by age band",
            caption=(
                "Age bands are ordered. The comparison is descriptive and "
                "does not show a causal effect."
            ),
        )

    with state_tab:
        state_table = churn_rate_table(filtered, "state", min_n=SMALL_SAMPLE)
        show_all = st.toggle(
            "Show all states",
            value=False,
            key="segments-show-all-states",
            help="When off, the table shows the states with the most relationships.",
        )
        shown = state_table if show_all else state_table.head(15)
        render_rate_table(
            shown,
            segment_label="State",
            caption=(
                f"Showing {len(shown):,} of {len(state_table):,} states. "
                "States with fewer relationships have wider intervals."
            ),
        )
        render_rate_bar(
            shown.sort_values("rate", ascending=False, kind="stable"),
            title="Current churn rate by state",
            height=480,
        )

    render_notebook_charts(
        "Analysis",
        [
            "analysis_04.png",
            "analysis_05.png",
            "analysis_06.png",
            "analysis_07.png",
        ],
        [
            "Provider differences at both grains",
            "Age and dependents at both grains",
            "Current customer churn by state/UT (n ≥ 100 current relationships)",
            "Tenure and current customer churn",
        ],
    )
