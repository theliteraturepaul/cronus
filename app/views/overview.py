"""Overview page: active snapshot and dual-grain churn measures."""

from __future__ import annotations

import streamlit as st
from shared import (
    active_summary_state,
    current_frame_for,
    page_header,
    render_dual_grain_chart,
    render_empty_dataset,
    render_notebook_charts,
    render_profile,
    render_rate_bar,
    section_header,
)

from cronus.analytics import (
    age_band_table,
    churn_rate_table,
    registration_cohort_table,
    tenure_band_table,
    usage_quartile_table,
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

    frame = current_frame_for(summary)
    if frame is None:
        return

    render_profile(summary)

    section_header(
        "Dual-grain churn",
        "Two rates with different denominators. Keep them separate.",
    )
    left, right = st.columns(2)
    with left:
        st.metric(
            "Relationship churn — all history",
            f"{summary.relationship_churn_count:,} of {summary.relationship_count:,} "
            f"({summary.relationship_churn_rate:.2f}%)",
        )
        st.caption(
            "This rate covers every customer-provider relationship in the snapshot. "
            "It includes historical relationships."
        )
    with right:
        st.metric(
            "Current customer churn — latest only",
            f"{summary.current_churn_count:,} of {summary.current_relationship_count:,} "
            f"({summary.current_churn_rate:.2f}%)",
        )
        st.caption(
            "This rate covers one latest relationship per customer. "
            "It is the rate used for current-customer statements and model evidence."
        )

    render_dual_grain_chart(
        relationship_count=summary.relationship_count,
        relationship_churned=summary.relationship_churn_count,
        current_count=summary.current_relationship_count,
        current_churned=summary.current_churn_count,
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

    st.divider()
    st.caption(
        "All comparisons below use the latest relationship per customer. "
        "Historical relationships are excluded."
    )

    section_header("Current churn by provider", "Live computation from the active dataset.")
    provider_table = churn_rate_table(frame, "telecom_partner", min_n=30)
    render_rate_bar(provider_table, title="Current churn rate by provider", height=320)

    section_header("Current churn by gender", "Live computation from the active dataset.")
    gender_table = churn_rate_table(frame, "gender", min_n=30)
    render_rate_bar(gender_table, title="Current churn rate by gender", height=280)

    section_header("Current churn by age band", "Live computation from the active dataset.")
    age_table = age_band_table(frame)
    render_rate_bar(age_table, title="Current churn rate by age band", height=300)

    section_header("Current churn by tenure band", "Live computation from the active dataset.")
    tenure_table = tenure_band_table(frame)
    render_rate_bar(tenure_table, title="Current churn rate by tenure band", height=300)

    section_header("Current churn by usage quartile", "Live computation from the active dataset.")
    for column, label in [("calls_made", "Calls"), ("sms_sent", "SMS"), ("data_used", "Data")]:
        try:
            usage_table = usage_quartile_table(frame, column)
        except ValueError:
            continue
        render_rate_bar(
            usage_table,
            title=f"Current churn rate by {label.lower()} quartile",
            height=220,
        )

    section_header("Quarterly churn trend", "Live computation from the active dataset.")
    cohort_table = registration_cohort_table(frame)
    render_rate_bar(cohort_table, title="Current churn rate by registration year", height=300)

    section_header(
        "Where to look next",
        "Each page keeps the same current-frame definition.",
    )
    st.markdown(
        "- **Providers and segments** compares current churn across providers, "
        "gender, age bands, and states.\n"
        "- **Usage and tenure** shows current churn by tenure band, usage quartile, "
        "registration cohort, and rank correlation.\n"
        "- **Model performance** reports the fixed baseline holdout evidence and "
        "threshold policies.\n"
        "- **Churn predictions** ranks current relationships and exports the "
        "scored queue with its threshold.\n"
        "- **Power BI dashboard** opens the published report or the packaged PBIX."
    )
    st.caption(
        "Comparisons on this dashboard are descriptive. The snapshot does not "
        "identify causes of churn."
    )

    render_notebook_charts(
        "Analysis",
        [
            "analysis_01.png",
            "analysis_02.png",
            "analysis_03.png",
            "analysis_04.png",
            "analysis_05.png",
            "analysis_06.png",
            "analysis_07.png",
            "analysis_08.png",
            "analysis_09.png",
            "analysis_10.png",
            "analysis_11.png",
            "analysis_12.png",
        ],
        [
            "Grain and composition of the canonical snapshot",
            "Dual churn measures and the historical construction",
            "Distributions of current relationship attributes (n = 8,860)",
            "Provider differences at both grains",
            "Age and dependents at both grains",
            "Current customer churn by state/UT (n ≥ 100 current relationships)",
            "Tenure and current customer churn",
            "Current churn by usage and salary quartile (n = 8,860)",
            "Usage distributions by current churn status",
            "Spearman correlations on current relationships",
            "Registration volume and current churn by cohort",
            "Current churn by provider and calls quartile",
        ],
    )
