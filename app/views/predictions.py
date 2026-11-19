"""Churn predictions page: scored review queue at a fixed threshold policy."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    page_header,
    render_empty_dataset,
    render_notebook_charts,
    scores_for,
    scoring_model_for,
    section_header,
)

from cronus.modeling.serving import (
    THRESHOLD_POLICIES,
    ThresholdPolicy,
    summarize_scores,
)


def _selected_policy() -> ThresholdPolicy:
    labels = {
        f"{policy.label} — threshold {policy.threshold:.4f}": policy
        for policy in THRESHOLD_POLICIES
    }
    selected = st.radio(
        "Threshold policy",
        options=list(labels),
        index=0,
        horizontal=True,
        key="predictions-threshold-policy",
    )
    return labels[selected]


def _export_frame(
    scored: pd.DataFrame,
    *,
    policy: ThresholdPolicy,
    dataset_name: str,
    as_of_date: str,
) -> pd.DataFrame:
    export = scored.copy(deep=True)
    export["threshold_policy"] = policy.label
    export["dataset_name"] = dataset_name
    export["as_of_date"] = as_of_date
    return export


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Churn predictions",
        "A ranked review queue for current customer-provider relationships.",
        summary,
        chips=("Ranked queue", "In-sample scores"),
    )

    if not ok:
        return
    if summary is None:
        render_empty_dataset()
        return

    section_header(
        "Threshold policy",
        "Every score, display, and export carries the selected threshold.",
    )
    policy = _selected_policy()
    st.markdown(f"**{policy.label}** · threshold `{policy.threshold:.4f}`")
    st.caption(policy.note)

    model = scoring_model_for(summary)
    if model is None:
        return

    scored = scores_for(summary, policy.threshold)
    if scored is None:
        return

    score_summary = summarize_scores(scored)
    elevated_count = int((scored["review_priority"] == "Elevated").sum())
    st.caption(
        f"Model fitted on {model.current_rows:,} current relationships at "
        f"{model.fitted_at:%d %b %Y %H:%M UTC}. "
        f"The decision threshold is {policy.threshold:.4f}."
    )
    st.caption(
        "The model fits the active current frame and scores the same rows. "
        "These scores are in-sample. The Phase 3 holdout metrics remain the "
        "out-of-sample evidence."
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Scored relationships", f"{score_summary.scored_rows:,}")
    col2.metric(
        f"Flagged at {policy.threshold:.4f}",
        f"{score_summary.flagged_count:,} ({score_summary.flagged_rate * 100:.2f}%)",
    )
    col3.metric(
        f"Elevated at {policy.threshold:.4f}",
        f"{elevated_count:,}",
    )
    col4.metric(
        f"Mean score at {policy.threshold:.4f}",
        f"{score_summary.mean_probability:.4f}",
    )

    st.caption(
        f"Median score {score_summary.median_probability:.4f}. "
        f"A relationship is flagged when its score is at or above "
        f"{policy.threshold:.4f}."
    )

    section_header(
        "Review queue",
        "Filter the queue and choose how many rows to show.",
    )
    with st.expander("Review queue filters", expanded=True):
        left, right = st.columns(2)
        with left:
            provider_options = sorted(scored["telecom_partner"].unique().tolist())
            providers = st.multiselect(
                "Provider",
                options=provider_options,
                key="predictions-providers",
                placeholder="All providers",
            )
        with right:
            state_options = sorted(scored["state"].unique().tolist())
            states = st.multiselect(
                "State",
                options=state_options,
                key="predictions-states",
                placeholder="All states",
            )
        priority_options = ["High", "Elevated", "Low"]
        priorities = st.multiselect(
            "Review priority",
            options=priority_options,
            key="predictions-priorities",
            placeholder="All priorities",
        )

    filtered = scored
    if providers:
        filtered = filtered.loc[filtered["telecom_partner"].isin(providers)]
    if states:
        filtered = filtered.loc[filtered["state"].isin(states)]
    if priorities:
        filtered = filtered.loc[filtered["review_priority"].isin(priorities)]

    st.markdown(
        f"**Showing scores at threshold {policy.threshold:.4f}** · "
        f"{len(filtered):,} of {len(scored):,} relationships"
    )

    if filtered.empty:
        st.warning("No scored relationships match the selected filters.")
        return

    max_rows = max(1, len(filtered))
    top_n = st.slider(
        "Rows to display",
        min_value=1,
        max_value=max_rows,
        value=min(100, max_rows),
        step=1,
        key="predictions-top-n",
    )

    display = filtered.head(top_n).copy(deep=True)
    display["churn_probability %"] = (display["churn_probability"] * 100).round(2)
    display["predicted_churn"] = display["predicted_churn"].map({True: "Yes", False: "No"})
    display = display.rename(
        columns={
            "score_rank": "Rank",
            "customer_id": "Customer ID",
            "telecom_partner": "Provider",
            "state": "State",
            "tenure_days": "Tenure days",
            "calls_made": "Calls",
            "sms_sent": "SMS",
            "data_used": "Data",
            "churn_probability %": "Score %",
            "predicted_churn": "Flagged",
            "review_priority": "Priority",
            "threshold": "Threshold",
        }
    )
    st.dataframe(
        display.loc[
            :,
            [
                "Rank",
                "Customer ID",
                "Provider",
                "State",
                "Tenure days",
                "Calls",
                "SMS",
                "Data",
                "Score %",
                "Flagged",
                "Priority",
                "Threshold",
            ],
        ],
        hide_index=True,
        width="stretch",
        height=520,
        column_config={
            "Score %": st.column_config.NumberColumn(format="%.2f"),
            "Threshold": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    st.caption(
        f"Every row carries threshold {policy.threshold:.4f}. "
        "A flag is a model decision, not an observed churn event."
    )

    export = _export_frame(
        filtered,
        policy=policy,
        dataset_name=summary.dataset_name,
        as_of_date=summary.as_of_date.isoformat(),
    )
    export_full = _export_frame(
        scored,
        policy=policy,
        dataset_name=summary.dataset_name,
        as_of_date=summary.as_of_date.isoformat(),
    )
    section_header(
        "Export",
        "Both files include the threshold, policy label, dataset name, and snapshot date.",
    )
    filename = f"churnlab_churn_scores_threshold_{policy.threshold:.4f}"
    download_left, download_right = st.columns(2)
    with download_left:
        st.download_button(
            "Download filtered queue (CSV)",
            data=export.to_csv(index=False).encode("utf-8"),
            file_name=f"{filename}_filtered.csv",
            mime="text/csv",
            key=f"predictions-download-filtered-{policy.threshold:.4f}",
        )
    with download_right:
        st.download_button(
            "Download full queue (CSV)",
            data=export_full.to_csv(index=False).encode("utf-8"),
            file_name=f"{filename}_full.csv",
            mime="text/csv",
            key=f"predictions-download-full-{policy.threshold:.4f}",
        )
    st.caption(
        f"Both exports include a threshold column set to {policy.threshold:.4f}, "
        f"the policy label, the dataset name, and the snapshot date."
    )

    st.divider()
    st.caption(
        "The queue uses only the latest relationship per customer. "
        "Historical relationships are excluded. Scores rank relationships for "
        "review. They do not predict an individual customer's fate and do not "
        "estimate a causal effect."
    )

    render_notebook_charts(
        "model performance and predictions",
        [
            "modeling/modeling_01.png",
            "modeling/modeling_02.png",
            "modeling/modeling_03.png",
            "modeling/modeling_07.png",
            "modeling/modeling_09.png",
            "modeling/modeling_10.png",
        ],
        [
            "Model comparison: PR-AUC and ROC-AUC",
            "Precision-recall curves",
            "ROC curves",
            "Calibration plot",
            "Temporal check: threshold selection",
            "Confusion matrix at default vs selected threshold",
        ],
    )
