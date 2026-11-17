"""Overview page: active snapshot and dual-grain churn measures."""

from __future__ import annotations

import streamlit as st
from shared import (
    active_summary_state,
    page_header,
    render_empty_dataset,
    render_profile,
)


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Overview",
        "Current customer-provider relationships, snapshot context, and dual-grain churn.",
        summary,
    )

    if not ok:
        return
    if summary is None:
        render_empty_dataset()
        return

    render_profile(summary)

    st.divider()
    st.subheader("Dual-grain churn")
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

    st.warning(
        f"Do not present {relationship_rate:.2f}% as the current customer churn rate. "
        f"The current customer churn rate is {current_rate:.2f}%."
    )

    st.subheader("Snapshot context")
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
    st.subheader("Where to look next")
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
