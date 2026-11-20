"""Model performance page: fixed baseline evidence and threshold policies."""

from __future__ import annotations

import pandas as pd
import streamlit as st
from shared import (
    load_active_summary,
    page_header,
    render_calibration_chart,
    render_importance_chart,
    render_metric_comparison_chart,
    render_recall_chart,
    section_header,
)

from cronus.modeling.serving import (
    CALIBRATION_BINS,
    DEFAULT_THRESHOLD_POLICY,
    MODEL_CARD,
    PERMUTATION_IMPORTANCE,
    SUBGROUP_RECALL,
    TEMPORAL_CHECK,
    THRESHOLD_POLICIES,
)

THRESHOLD = DEFAULT_THRESHOLD_POLICY.threshold


def _metric_interval(value: float, low: float, high: float) -> str:
    return f"{value:.4f} [{low:.4f}, {high:.4f}]"


def render() -> None:
    try:
        summary = load_active_summary()
    except Exception:
        summary = None

    page_header(
        "Model performance",
        "Fixed baseline holdout evidence for the current-relationship churn model.",
        summary,
        chips=("Fixed evidence", "Holdout"),
    )

    st.info(
        "The figures on this page come from the baseline snapshot. "
        "The app refits the same final model on the active current frame for scoring. "
        "It does not retune the model, change the features, or reselect a threshold."
    )

    section_header("Model card")
    card_rows = [
        ("Model", MODEL_CARD.model_name),
        ("Features", f"{MODEL_CARD.feature_count} current-relationship features"),
        ("Relationship count feature", "Excluded"),
        ("Baseline snapshot", f"{MODEL_CARD.baseline_as_of_date:%d %b %Y}"),
        ("Training rows", f"{MODEL_CARD.baseline_rows:,} current relationships"),
        ("Training churn events", f"{MODEL_CARD.baseline_events:,}"),
        ("Training prevalence", f"{MODEL_CARD.baseline_prevalence * 100:.2f}%"),
        ("Fixed default threshold", f"{THRESHOLD:.4f}"),
    ]
    st.dataframe(
        pd.DataFrame(card_rows, columns=["Item", "Value"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "The model ranks current customer-provider relationships. It does not "
        "estimate the effect of a feature on churn."
    )

    section_header("Holdout and cross-validation metrics")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Holdout PR-AUC",
        f"{MODEL_CARD.holdout_pr_auc:.4f}",
        help=(
            f"95% bootstrap interval {MODEL_CARD.holdout_pr_auc_low:.4f} to "
            f"{MODEL_CARD.holdout_pr_auc_high:.4f}."
        ),
    )
    col2.metric(
        "Holdout ROC-AUC",
        f"{MODEL_CARD.holdout_roc_auc:.4f}",
        help=(
            f"95% bootstrap interval {MODEL_CARD.holdout_roc_auc_low:.4f} to "
            f"{MODEL_CARD.holdout_roc_auc_high:.4f}."
        ),
    )
    col3.metric(
        "Holdout Brier",
        f"{MODEL_CARD.holdout_brier:.4f}",
        help=(
            f"95% bootstrap interval {MODEL_CARD.holdout_brier_low:.4f} to "
            f"{MODEL_CARD.holdout_brier_high:.4f}."
        ),
    )
    col4.metric(
        "Holdout prevalence",
        f"{MODEL_CARD.baseline_prevalence * 100:.2f}%",
        help="Share of churned relationships in the holdout split.",
    )

    pr_interval = _metric_interval(
        MODEL_CARD.holdout_pr_auc,
        MODEL_CARD.holdout_pr_auc_low,
        MODEL_CARD.holdout_pr_auc_high,
    )
    roc_interval = _metric_interval(
        MODEL_CARD.holdout_roc_auc,
        MODEL_CARD.holdout_roc_auc_low,
        MODEL_CARD.holdout_roc_auc_high,
    )
    brier_interval = _metric_interval(
        MODEL_CARD.holdout_brier,
        MODEL_CARD.holdout_brier_low,
        MODEL_CARD.holdout_brier_high,
    )
    st.caption(
        f"Cross-validation: PR-AUC {MODEL_CARD.cv_pr_auc:.4f} ± "
        f"{MODEL_CARD.cv_pr_auc_std:.4f}, ROC-AUC {MODEL_CARD.cv_roc_auc:.4f}, "
        f"Brier {MODEL_CARD.cv_brier:.4f}. "
        f"Holdout intervals: PR-AUC {pr_interval}, "
        f"ROC-AUC {roc_interval}, Brier {brier_interval}."
    )

    render_metric_comparison_chart(
        [
            {"Metric": "PR-AUC", "Source": "Cross-validation", "Value": MODEL_CARD.cv_pr_auc},
            {"Metric": "PR-AUC", "Source": "Holdout", "Value": MODEL_CARD.holdout_pr_auc},
            {"Metric": "PR-AUC", "Source": "Temporal", "Value": TEMPORAL_CHECK.pr_auc},
            {"Metric": "ROC-AUC", "Source": "Cross-validation", "Value": MODEL_CARD.cv_roc_auc},
            {"Metric": "ROC-AUC", "Source": "Holdout", "Value": MODEL_CARD.holdout_roc_auc},
            {"Metric": "ROC-AUC", "Source": "Temporal", "Value": TEMPORAL_CHECK.roc_auc},
            {"Metric": "Brier", "Source": "Cross-validation", "Value": MODEL_CARD.cv_brier},
            {"Metric": "Brier", "Source": "Holdout", "Value": MODEL_CARD.holdout_brier},
            {"Metric": "Brier", "Source": "Temporal", "Value": TEMPORAL_CHECK.brier},
        ]
    )
    st.caption(
        "Bars group the three evidence sources. Higher is better for PR-AUC and "
        "ROC-AUC. Lower is better for Brier."
    )

    section_header("Threshold policies")
    policy_frame = pd.DataFrame(
        [
            {
                "Policy": policy.label,
                "Threshold": policy.threshold,
                "Precision": policy.precision,
                "Recall": policy.recall,
                "F1": policy.f1,
                "Note": policy.note,
            }
            for policy in THRESHOLD_POLICIES
        ]
    )
    st.dataframe(
        policy_frame,
        hide_index=True,
        width="stretch",
        column_config={
            "Threshold": st.column_config.NumberColumn(format="%.4f"),
            "Precision": st.column_config.NumberColumn(format="%.3f"),
            "Recall": st.column_config.NumberColumn(format="%.3f"),
            "F1": st.column_config.NumberColumn(format="%.3f"),
        },
    )
    st.caption(
        "Precision, recall, and F1 come from the holdout at the threshold "
        "shown in the same row. The default policy is max-F1."
    )

    section_header(f"Confusion matrix at threshold {THRESHOLD:.4f}")
    confusion = pd.DataFrame(
        [
            [MODEL_CARD.true_negative, MODEL_CARD.false_positive],
            [MODEL_CARD.false_negative, MODEL_CARD.true_positive],
        ],
        index=["Actual retained", "Actual churned"],
        columns=["Predicted retained", "Predicted churned"],
    )
    st.dataframe(confusion, width="stretch")
    precision = MODEL_CARD.true_positive / (MODEL_CARD.true_positive + MODEL_CARD.false_positive)
    recall = MODEL_CARD.true_positive / (MODEL_CARD.true_positive + MODEL_CARD.false_negative)
    specificity = MODEL_CARD.true_negative / (MODEL_CARD.true_negative + MODEL_CARD.false_positive)
    f1 = 2 * precision * recall / (precision + recall)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric(f"Precision at {THRESHOLD:.4f}", f"{precision:.4f}")
    col2.metric(f"Recall at {THRESHOLD:.4f}", f"{recall:.4f}")
    col3.metric(f"Specificity at {THRESHOLD:.4f}", f"{specificity:.4f}")
    col4.metric(f"F1 at {THRESHOLD:.4f}", f"{f1:.4f}")
    st.caption(
        f"At threshold {THRESHOLD:.4f}, the model flags "
        f"{MODEL_CARD.true_positive + MODEL_CARD.false_positive:,} of "
        f"{MODEL_CARD.baseline_rows:,} holdout relationships and catches "
        f"{MODEL_CARD.true_positive:,} of "
        f"{MODEL_CARD.true_positive + MODEL_CARD.false_negative:,} churners."
    )

    st.warning(
        f"At the default threshold 0.5000, the model catches only "
        f"{MODEL_CARD.default_threshold_true_positives} of "
        f"{MODEL_CARD.default_threshold_churners} holdout churners. "
        f"Use {THRESHOLD:.4f} with the displayed precision and recall."
    )

    section_header("Permutation importance on holdout PR-AUC")
    importance = pd.DataFrame(
        PERMUTATION_IMPORTANCE,
        columns=["Feature", "Mean drop in PR-AUC", "Std"],
    )
    render_importance_chart(importance)
    st.dataframe(
        importance,
        hide_index=True,
        width="stretch",
        column_config={
            "Mean drop in PR-AUC": st.column_config.NumberColumn(format="%.4f"),
            "Std": st.column_config.NumberColumn(format="%.4f"),
        },
    )
    st.caption(
        "A value shows the drop in holdout PR-AUC when that feature is shuffled. "
        "A value near zero or below zero means the holdout does not show a "
        "measurable contribution."
    )

    section_header(f"Subgroup recall at threshold {THRESHOLD:.4f}")
    subgroup = pd.DataFrame(SUBGROUP_RECALL, columns=["Segment", "Recall"])
    subgroup["Recall %"] = (subgroup["Recall"] * 100).round(2)
    render_recall_chart(subgroup, threshold=THRESHOLD)
    st.dataframe(
        subgroup[["Segment", "Recall %"]],
        hide_index=True,
        width="stretch",
        column_config={"Recall %": st.column_config.NumberColumn(format="%.2f")},
    )
    st.caption(
        "Recall is computed on the holdout at the threshold shown above. "
        "Several segments have few churn events, so these values have wide "
        "uncertainty. Use them to plan review capacity."
    )

    section_header("Calibration on the holdout")
    calibration = pd.DataFrame(
        CALIBRATION_BINS,
        columns=["N", "Mean predicted", "Observed rate", "Gap"],
    )
    calibration["Mean predicted %"] = (calibration["Mean predicted"] * 100).round(2)
    calibration["Observed rate %"] = (calibration["Observed rate"] * 100).round(2)

    render_calibration_chart(calibration)
    st.dataframe(
        calibration[["N", "Mean predicted %", "Observed rate %", "Gap"]],
        hide_index=True,
        width="stretch",
        column_config={
            "Mean predicted %": st.column_config.NumberColumn(format="%.2f"),
            "Observed rate %": st.column_config.NumberColumn(format="%.2f"),
            "Gap": st.column_config.NumberColumn(format="%+.4f"),
        },
    )
    st.caption(
        f"The largest calibration gap is {MODEL_CARD.calibration_max_gap:+.4f}. "
        "Probabilities are useful for ranking. Do not read them as exact "
        "individual churn rates."
    )

    section_header("Temporal check")
    temporal_rows = [
        ("Train years", "–".join(str(year) for year in TEMPORAL_CHECK.train_years)),
        ("Test years", "–".join(str(year) for year in TEMPORAL_CHECK.test_years)),
        ("Selected threshold", f"{TEMPORAL_CHECK.threshold:.4f}"),
        ("Test PR-AUC", f"{TEMPORAL_CHECK.pr_auc:.4f}"),
        ("Test ROC-AUC", f"{TEMPORAL_CHECK.roc_auc:.4f}"),
        ("Test Brier", f"{TEMPORAL_CHECK.brier:.4f}"),
        ("Test prevalence", f"{TEMPORAL_CHECK.prevalence * 100:.2f}%"),
        ("Test precision", f"{TEMPORAL_CHECK.precision:.4f}"),
        ("Test recall", f"{TEMPORAL_CHECK.recall:.4f}"),
        ("Test F1", f"{TEMPORAL_CHECK.f1:.4f}"),
    ]
    st.dataframe(
        pd.DataFrame(temporal_rows, columns=["Item", "Value"]),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        "The temporal check trains on 2020–2021 registrations and tests on "
        "2022–2023 registrations. It selects the threshold on the older period "
        "only. Precision, recall, and F1 use that threshold."
    )

    st.divider()
    st.caption(
        "The model does not predict an individual customer's fate. "
        "It does not estimate a causal effect. The threshold must travel "
        "with every score and export."
    )
