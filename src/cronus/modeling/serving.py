"""Final-model configuration and batch scoring for the Streamlit application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Literal

import numpy as np
import pandas as pd

from cronus.modeling.features import prepare_current_frame
from cronus.modeling.training import FittedModel, fit_final_model, predict_churn

FINAL_MODEL_NAME: Literal["logistic"] = "logistic"
FINAL_INCLUDE_RELATIONSHIP_COUNT = False
FINAL_MODEL_PARAMS = MappingProxyType({"classifier__C": 0.1})
FINAL_THRESHOLD = 0.1840
HIGH_RECALL_THRESHOLD = 0.0981


@dataclass(frozen=True)
class ThresholdPolicy:
    """One fixed baseline threshold policy."""

    key: str
    label: str
    threshold: float
    precision: float
    recall: float
    f1: float
    note: str


THRESHOLD_POLICIES: tuple[ThresholdPolicy, ...] = (
    ThresholdPolicy(
        key="max_f1",
        label="Max-F1 (recommended)",
        threshold=FINAL_THRESHOLD,
        precision=0.2405,
        recall=0.3373,
        f1=0.2808,
        note="Selected on out-of-fold predictions. Default review policy.",
    ),
    ThresholdPolicy(
        key="recall_70",
        label="70% recall floor",
        threshold=HIGH_RECALL_THRESHOLD,
        precision=0.172,
        recall=0.669,
        f1=0.273,
        note=(
            "Flags more relationships and produces more false positives. "
            "Use only when review capacity is higher."
        ),
    ),
)

DEFAULT_THRESHOLD_POLICY = THRESHOLD_POLICIES[0]


@dataclass(frozen=True)
class ModelCard:
    """Documented holdout evidence for the baseline snapshot."""

    model_name: str = "Logistic regression with L2 penalty"
    feature_count: int = 10
    baseline_rows: int = 8_860
    baseline_events: int = 847
    baseline_prevalence: float = 0.0956
    baseline_relationship_count: int = 10_000
    baseline_as_of_date: date = date(2023, 5, 4)
    cv_pr_auc: float = 0.2662
    cv_pr_auc_std: float = 0.0493
    cv_roc_auc: float = 0.7497
    cv_brier: float = 0.0794
    holdout_pr_auc: float = 0.2312
    holdout_pr_auc_low: float = 0.1909
    holdout_pr_auc_high: float = 0.2926
    holdout_roc_auc: float = 0.7295
    holdout_roc_auc_low: float = 0.6884
    holdout_roc_auc_high: float = 0.7654
    holdout_brier: float = 0.0806
    holdout_brier_low: float = 0.0778
    holdout_brier_high: float = 0.0834
    true_negative: int = 1_423
    false_positive: int = 180
    false_negative: int = 112
    true_positive: int = 57
    default_threshold_true_positives: int = 2
    default_threshold_churners: int = 169
    calibration_max_gap: float = -0.036


MODEL_CARD = ModelCard()

PERMUTATION_IMPORTANCE: tuple[tuple[str, float, float], ...] = (
    ("telecom_partner", 0.0434, 0.0090),
    ("data_used", 0.0320, 0.0168),
    ("calls_made", 0.0231, 0.0077),
    ("tenure_days", 0.0178, 0.0095),
    ("estimated_salary", 0.0119, 0.0072),
    ("num_dependents", 0.0118, 0.0082),
    ("sms_sent", 0.0020, 0.0057),
    ("gender", -0.0002, 0.0007),
    ("age", -0.0005, 0.0003),
    ("state", -0.0007, 0.0049),
)

SUBGROUP_RECALL: tuple[tuple[str, float], ...] = (
    ("BSNL", 0.577),
    ("Airtel", 0.375),
    ("Vodafone", 0.178),
    ("Reliance Jio", 0.125),
    ("Highest calls quartile", 0.000),
)

CALIBRATION_BINS: tuple[tuple[int, float, float, float], ...] = (
    (178, 0.008, 0.011, 0.003),
    (177, 0.022, 0.028, 0.006),
    (177, 0.034, 0.051, 0.017),
    (177, 0.047, 0.045, -0.002),
    (177, 0.063, 0.073, 0.011),
    (177, 0.081, 0.085, 0.003),
    (177, 0.103, 0.096, -0.007),
    (177, 0.132, 0.096, -0.036),
    (177, 0.177, 0.209, 0.032),
    (178, 0.290, 0.258, -0.032),
)


@dataclass(frozen=True)
class TemporalCheck:
    """Documented temporal holdout check."""

    train_years: tuple[int, ...] = (2020, 2021)
    test_years: tuple[int, ...] = (2022, 2023)
    threshold: float = 0.1410
    pr_auc: float = 0.2776
    roc_auc: float = 0.7450
    brier: float = 0.0941
    prevalence: float = 0.1155
    precision: float = 0.2265
    recall: float = 0.6212
    f1: float = 0.3320


TEMPORAL_CHECK = TemporalCheck()


@dataclass(frozen=True)
class ScoringModel:
    """A fitted scoring pipeline and its dataset metadata."""

    model: FittedModel
    dataset_id: str
    current_rows: int
    threshold: float
    fitted_at: datetime


@dataclass(frozen=True)
class ScoreSummary:
    """Aggregate counts for one scored current-relationship frame."""

    threshold: float
    scored_rows: int
    flagged_count: int
    flagged_rate: float
    high_priority_count: int
    mean_probability: float
    median_probability: float


def _assert_current_frame(frame: pd.DataFrame) -> None:
    if frame.empty:
        raise ValueError("The current-relationship frame is empty")
    required = {"customer_id", "is_latest_relationship"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing current-grain columns: {', '.join(missing)}")
    if not frame["is_latest_relationship"].astype(bool).all():
        raise ValueError("The frame contains historical relationships")
    if frame["customer_id"].duplicated().any():
        duplicates = int(frame["customer_id"].duplicated().sum())
        raise ValueError(
            f"The current-relationship frame contains {duplicates} duplicate customer(s)"
        )


def fit_scoring_model(
    current_frame: pd.DataFrame,
    *,
    dataset_id: str,
) -> ScoringModel:
    """Fit the final baseline pipeline on the complete active current frame."""

    current = prepare_current_frame(current_frame)
    if current.empty:
        raise ValueError("The current-relationship frame is empty")

    model = fit_final_model(
        current,
        model_name=FINAL_MODEL_NAME,
        include_relationship_count=FINAL_INCLUDE_RELATIONSHIP_COUNT,
        params=FINAL_MODEL_PARAMS,
        threshold=FINAL_THRESHOLD,
    )
    return ScoringModel(
        model=model,
        dataset_id=dataset_id,
        current_rows=len(current),
        threshold=FINAL_THRESHOLD,
        fitted_at=datetime.now(UTC),
    )


def score_current_relationships(
    scoring_model: ScoringModel,
    frame: pd.DataFrame,
    *,
    threshold: float | None = None,
) -> pd.DataFrame:
    """Return a ranked review queue for current customer-provider relationships."""

    _assert_current_frame(frame)
    selected_threshold = scoring_model.threshold if threshold is None else float(threshold)
    if not 0.0 <= selected_threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")

    required = (
        "customer_id",
        "telecom_partner",
        "state",
        "tenure_days",
        "calls_made",
        "sms_sent",
        "data_used",
    )
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing scoring columns: {', '.join(missing)}")

    probabilities = predict_churn(scoring_model.model, frame)
    priority = np.where(
        probabilities >= selected_threshold,
        "High",
        np.where(probabilities >= selected_threshold / 2.0, "Elevated", "Low"),
    )

    scored = pd.DataFrame(
        {
            "customer_id": frame["customer_id"].astype(str).to_numpy(),
            "telecom_partner": frame["telecom_partner"].astype(str).to_numpy(),
            "state": frame["state"].astype(str).to_numpy(),
            "tenure_days": frame["tenure_days"].astype("int64").to_numpy(),
            "calls_made": frame["calls_made"].astype("int64").to_numpy(),
            "sms_sent": frame["sms_sent"].astype("int64").to_numpy(),
            "data_used": frame["data_used"].astype("int64").to_numpy(),
            "churn_probability": np.asarray(probabilities, dtype=float),
            "predicted_churn": np.asarray(probabilities >= selected_threshold, dtype=bool),
            "review_priority": priority.astype(str),
            "threshold": np.full(len(frame), selected_threshold, dtype=float),
        }
    )
    scored = scored.sort_values(
        ["churn_probability", "customer_id"],
        ascending=[False, True],
        kind="stable",
    ).reset_index(drop=True)
    scored.insert(0, "score_rank", np.arange(1, len(scored) + 1, dtype=int))
    return scored


def summarize_scores(scored: pd.DataFrame) -> ScoreSummary:
    """Summarize a scored review queue."""

    if scored.empty:
        raise ValueError("The scored frame is empty")
    required = {"churn_probability", "predicted_churn", "review_priority", "threshold"}
    missing = sorted(required - set(scored.columns))
    if missing:
        raise ValueError(f"Missing score columns: {', '.join(missing)}")

    thresholds = scored["threshold"].astype(float).unique()
    if len(thresholds) != 1:
        raise ValueError("The scored frame must contain exactly one threshold")

    scored_rows = len(scored)
    flagged_count = int(scored["predicted_churn"].astype(bool).sum())
    probabilities = scored["churn_probability"].astype(float)
    return ScoreSummary(
        threshold=float(thresholds[0]),
        scored_rows=scored_rows,
        flagged_count=flagged_count,
        flagged_rate=flagged_count / scored_rows,
        high_priority_count=int((scored["review_priority"] == "High").sum()),
        mean_probability=float(probabilities.mean()),
        median_probability=float(probabilities.median()),
    )
