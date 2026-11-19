"""Overview page: active snapshot and dual-grain churn measures."""

from __future__ import annotations

import streamlit as st
from shared import (
    active_summary_state,
    page_header,
    render_empty_dataset,
    render_notebook_charts,
    render_profile,
    section_header,
)


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Overview",
        "Current customer-provider relationships, snapshot context, and dual-grain churn.",
        summary,
        chips=("Current relationships", "Dual-grain churn"),
    )

    if not ok:
        return
    if summary is None:
        render_empty_dataset()
        return

    render_profile(summary)

    section_header(
        "Dual-grain churn",
        "Two rates with different denominators. Keep them separate.",
    )
    relationship_rate = summary.relationship_churn_rate
    current_rate = summary.current_churn_rate

    left, right = st.columns(2)
    with left:
        st.metric(
            "Relationship churn — all history",
            f"{summary.relationship_churn_count:,} of {summary.relationship_count:,} "
            f"({relationship_rate:.2f}%)",
        )
        st.caption(
            "This rate covers every customer-provider relationship in the snapshot. "
            "It includes historical relationships."
        )
    with right:
        st.metric(
            "Current customer churn — latest only",
            f"{summary.current_churn_count:,} of {summary.current_relationship_count:,} "
            f"({current_rate:.2f}%)",
        )
        st.caption(
            "This rate covers one latest relationship per customer. "
            "It is the rate used for current-customer statements and model evidence."
        )

    section_header(
        "Snapshot context",
        "Coverage, customer base, and relationship structure in the active dataset.",
    )
    if summary.min_registration_date and summary.max_registration_date:
        registration_window = (
            f"**{summary.min_registration_date:%d %b %Y}** to "
            f"**{summary.max_registration_date:%d %b %Y}**"
        )
    else:
        registration_window = "unavailable"

    left, right = st.columns(2)
    with left:
        st.markdown(
            f"- Snapshot date: **{summary.as_of_date:%d %b %Y}**\n"
            f"- Registration window: {registration_window}\n"
            f"- Unique customers: **{summary.unique_customers:,}**\n"
            f"- Telecom partners: **{summary.partner_count}**"
        )
    with right:
        st.markdown(
            f"- Historical relationships: **{summary.historical_relationships:,}**\n"
            f"- Current relationships: **{summary.current_relationship_count:,}**\n"
            f"- Multi-provider customers: **{summary.multi_relationship_customers:,}**\n"
            f"- Re-entry customer-provider pairs: **{summary.reentry_pairs:,}**"
        )

    st.caption(
        "A customer can hold more than one provider relationship over time. "
        "Churn is provider-specific. A returning customer-provider pair is a "
        "legitimate relationship, not a duplicate."
    )

    section_header(
        "Where to look next",
        "Each page keeps the same current-frame definition.",
    )
    st.markdown(
        "- **Providers and segments** compares current churn across providers, "
        "gender, age bands, and states.\n"
        "- **Usage and tenure** shows current churn by tenure band, usage quartile, "
        "registration cohort, and rank correlation.\n"
        "- **Model performance** reports the fixed Phase 3 holdout evidence and "
        "threshold policies.\n"
        "- **Churn predictions** ranks current relationships and exports the "
        "scored queue with its threshold."
    )
    st.caption(
        "Comparisons on this dashboard are descriptive. The snapshot does not "
        "identify causes of churn."
    )

    render_notebook_charts(
        "exploratory analysis",
        [
            "analysis/analysis_01.png",
            "analysis/analysis_02.png",
            "analysis/analysis_03.png",
            "analysis/analysis_04.png",
            "analysis/analysis_05.png",
            "analysis/analysis_06.png",
            "analysis/analysis_07.png",
            "analysis/analysis_08.png",
            "analysis/analysis_09.png",
            "analysis/analysis_10.png",
            "analysis/analysis_11.png",
            "analysis/analysis_12.png",
        ],
        [
            "Relationship vs current churn distribution",
            "Churn by provider and gender",
            "Age, salary, calls, SMS, data distributions",
            "Churn rate by provider and gender",
            "Churn rate by age band",
            "Churn rate by state",
            "Tenure and churn status distributions",
            "Churn rate by usage quartiles (calls, SMS, data)",
            "Spearman correlations with churn",
            "Quarterly churn trends",
            "Registration year vs churn",
            "Historical vs current relationship profile",
        ],
    )
