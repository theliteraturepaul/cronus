"""Power BI page: report access and a native preview of the five report pages."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st
from shared import (
    active_summary_state,
    current_frame_for,
    page_header,
    render_calibration_chart,
    render_dual_grain_chart,
    render_empty_dataset,
    render_importance_chart,
    render_rate_bar,
    render_score_histogram,
    scores_for,
    section_header,
)

from cronus.analytics import churn_rate_table, tenure_band_table, usage_quartile_table
from cronus.config import get_settings
from cronus.modeling.serving import (
    CALIBRATION_BINS,
    MODEL_CARD,
    PERMUTATION_IMPORTANCE,
    THRESHOLD_POLICIES,
    summarize_scores,
)

PBIX_PATH = Path(__file__).resolve().parents[2] / "PowerBI" / "project_dashboard.pbix"


def _render_pbix_download() -> None:
    if not PBIX_PATH.exists():
        st.warning("The PBIX file is not at the expected path.")
        return
    st.download_button(
        "Download project_dashboard.pbix",
        data=PBIX_PATH.read_bytes(),
        file_name="project_dashboard.pbix",
        mime="application/octet-stream",
        icon=":material/download:",
        width="stretch",
    )
    st.caption("Open the downloaded file in Power BI Desktop to view the full report.")


def _overview_preview(summary) -> None:
    frame = current_frame_for(summary)
    if frame is None:
        st.warning("The current relationships are not available.")
        return
    render_dual_grain_chart(
        relationship_count=summary.relationship_count,
        relationship_churned=summary.relationship_churn_count,
        current_count=summary.current_relationship_count,
        current_churned=summary.current_churn_count,
    )
    provider_table = churn_rate_table(frame, "telecom_partner", min_n=30)
    render_rate_bar(provider_table, title="Current churn rate by provider", height=320)


def _providers_preview(summary) -> None:
    frame = current_frame_for(summary)
    if frame is None:
        st.warning("The current relationships are not available.")
        return
    provider_table = churn_rate_table(frame, "telecom_partner", min_n=30)
    render_rate_bar(provider_table, title="Current churn rate by provider", height=320)
    gender_table = churn_rate_table(frame, "gender", min_n=30)
    render_rate_bar(gender_table, title="Current churn rate by gender", height=260)


def _usage_preview(summary) -> None:
    frame = current_frame_for(summary)
    if frame is None:
        st.warning("The current relationships are not available.")
        return
    tenure_table = tenure_band_table(frame)
    render_rate_bar(tenure_table, title="Current churn rate by tenure band", height=300)
    try:
        calls_table = usage_quartile_table(frame, "calls_made")
    except ValueError:
        st.info("This dataset does not support calls quartiles.")
        return
    render_rate_bar(calls_table, title="Current churn rate by calls quartile", height=240)


def _performance_preview() -> None:
    st.caption(
        f"Holdout PR-AUC {MODEL_CARD.holdout_pr_auc:.4f}, "
        f"ROC-AUC {MODEL_CARD.holdout_roc_auc:.4f}, "
        f"Brier {MODEL_CARD.holdout_brier:.4f}. "
        f"Training rows {MODEL_CARD.baseline_rows:,}."
    )
    importance = pd.DataFrame(
        PERMUTATION_IMPORTANCE,
        columns=["Feature", "Mean drop in PR-AUC", "Std"],
    )
    render_importance_chart(importance, height=320)
    calibration = pd.DataFrame(
        CALIBRATION_BINS,
        columns=["N", "Mean predicted", "Observed rate", "Gap"],
    )
    render_calibration_chart(calibration, height=320)


def _predictions_preview(summary) -> None:
    counts: list[str] = []
    for policy in THRESHOLD_POLICIES:
        scored = scores_for(summary, policy.threshold)
        if scored is None:
            return
        result = summarize_scores(scored)
        counts.append(
            f"{policy.label}: {result.flagged_count:,} flagged "
            f"({result.flagged_rate * 100:.2f}%) at {policy.threshold:.4f}"
        )
    st.markdown("\n".join(f"- {line}" for line in counts))

    scored = scores_for(summary, THRESHOLD_POLICIES[0].threshold)
    if scored is None:
        return
    render_score_histogram(scored, threshold=THRESHOLD_POLICIES[0].threshold, height=320)
    st.caption(
        "The Churn predictions page holds the full queue, its filters, and the "
        "threshold-tagged CSV exports."
    )


def render() -> None:
    summary, ok = active_summary_state()
    page_header(
        "Power BI dashboard",
        "Open the Power BI report or review a native preview of its five pages.",
        summary,
        chips=("Import mode", "Fixed baseline coefficients"),
    )

    st.caption(
        "The Power BI report uses Import mode against Neon Postgres. "
        "Power Query applies the fixed baseline logistic regression coefficients. "
        "The report has five pages: Overview, Providers and segments, Usage and tenure, "
        "Model performance, and Churn predictions."
    )

    if not ok:
        return

    settings = get_settings()
    powerbi_url = settings.powerbi_report_url
    if powerbi_url:
        section_header("Published report", "Embedded from Power BI Service.")
        st.components.v1.iframe(powerbi_url, height=800, scrolling=True)
    else:
        st.info(
            "No `POWERBI_REPORT_URL` is set. Download the packaged report file, or set the "
            "variable in `.env` or Streamlit secrets to embed a published report."
        )
        _render_pbix_download()

    if summary is None:
        st.divider()
        render_empty_dataset()
        return

    st.divider()
    section_header(
        "Native preview",
        "The same measures computed from the active dataset in this app.",
    )

    overview_tab, providers_tab, usage_tab, performance_tab, predictions_tab = st.tabs(
        [
            "Overview",
            "Providers and segments",
            "Usage and tenure",
            "Model performance",
            "Churn predictions",
        ]
    )
    with overview_tab:
        _overview_preview(summary)
    with providers_tab:
        _providers_preview(summary)
    with usage_tab:
        _usage_preview(summary)
    with performance_tab:
        _performance_preview()
    with predictions_tab:
        _predictions_preview(summary)
