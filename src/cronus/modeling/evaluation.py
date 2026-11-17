"""Metric, threshold and calibration helpers for churn evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline


@dataclass(frozen=True)
class MetricSummary:
    """Point estimates for one threshold on one evaluation set."""

    threshold: float
    prevalence: float
    pr_auc: float
    roc_auc: float
    accuracy: float
    precision: float
    recall: float
    f1: float
    brier: float
    log_loss: float
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int

    def as_dict(self) -> dict[str, float | int]:
        return asdict(self)


def _as_arrays(
    y_true: ArrayLike,
    y_prob: ArrayLike,
) -> tuple[NDArray[np.int_], NDArray[np.float64]]:
    target = np.asarray(y_true, dtype=int)
    probability = np.asarray(y_prob, dtype=float)
    if target.ndim != 1 or probability.ndim != 1:
        raise ValueError("y_true and y_prob must be one-dimensional")
    if len(target) != len(probability):
        raise ValueError("y_true and y_prob must have the same length")
    if len(target) == 0:
        raise ValueError("y_true and y_prob must not be empty")
    if not np.isin(target, [0, 1]).all():
        raise ValueError("y_true must contain only 0 and 1")
    if not np.isfinite(probability).all() or ((probability < 0) | (probability > 1)).any():
        raise ValueError("y_prob must contain finite values between 0 and 1")
    return target, probability


def _clip_unit(value: float) -> float:
    return float(min(max(value, 0.0), 1.0))


def evaluate_predictions(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    *,
    threshold: float = 0.5,
) -> MetricSummary:
    """Evaluate probabilities at one decision threshold."""

    target, probability = _as_arrays(y_true, y_prob)
    predicted = (probability >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(target, predicted, labels=[0, 1]).ravel()
    prevalence = float(target.mean())

    return MetricSummary(
        threshold=float(threshold),
        prevalence=prevalence,
        pr_auc=_clip_unit(float(average_precision_score(target, probability))),
        roc_auc=_clip_unit(float(roc_auc_score(target, probability))),
        accuracy=float(accuracy_score(target, predicted)),
        precision=float(precision_score(target, predicted, zero_division=0)),
        recall=float(recall_score(target, predicted, zero_division=0)),
        f1=float(f1_score(target, predicted, zero_division=0)),
        brier=_clip_unit(float(brier_score_loss(target, probability))),
        log_loss=float(log_loss(target, probability, labels=[0, 1])),
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        true_positive=int(tp),
    )


def select_threshold(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    *,
    min_recall: float | None = None,
) -> float:
    """Choose a threshold on out-of-fold predictions.

    By default the function maximises F1.  When ``min_recall`` is set, it
    returns the highest threshold that meets the recall floor.  Ties prefer the
    higher threshold, which predicts fewer positives.
    """

    target, probability = _as_arrays(y_true, y_prob)
    precision, recall, thresholds = precision_recall_curve(target, probability)
    precision = precision[:-1]
    recall = recall[:-1]
    if len(thresholds) == 0:
        return 0.5

    if min_recall is not None:
        eligible = np.flatnonzero(recall >= min_recall)
        if len(eligible) == 0:
            return float(thresholds[0])
        return float(thresholds[eligible[-1]])

    denominator = precision + recall
    scores = np.divide(
        2 * precision * recall,
        denominator,
        out=np.zeros_like(precision, dtype=float),
        where=denominator > 0,
    )
    best = np.flatnonzero(np.isclose(scores, scores.max()))
    return float(thresholds[best[-1]])


def threshold_table(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    *,
    thresholds: ArrayLike | None = None,
) -> pd.DataFrame:
    """Return precision, recall and volume over a threshold grid."""

    target, probability = _as_arrays(y_true, y_prob)
    grid = (
        np.round(np.arange(0.05, 0.96, 0.05), 2)
        if thresholds is None
        else np.asarray(thresholds, dtype=float)
    )
    rows: list[dict[str, float | int]] = []
    for threshold in grid:
        predicted = (probability >= threshold).astype(int)
        rows.append(
            {
                "threshold": float(threshold),
                "predicted_positive": int(predicted.sum()),
                "precision": float(precision_score(target, predicted, zero_division=0)),
                "recall": float(recall_score(target, predicted, zero_division=0)),
                "f1": float(f1_score(target, predicted, zero_division=0)),
            }
        )
    return pd.DataFrame(rows)


def bootstrap_intervals(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    *,
    threshold: float,
    n_resamples: int = 1_000,
    random_state: int = 42,
) -> dict[str, tuple[float, float]]:
    """Return stratified bootstrap 95% intervals for the main metrics."""

    target, probability = _as_arrays(y_true, y_prob)
    rng = np.random.default_rng(random_state)
    positive = np.flatnonzero(target == 1)
    negative = np.flatnonzero(target == 0)
    if len(positive) == 0 or len(negative) == 0:
        raise ValueError("Bootstrap intervals need both classes")

    values: dict[str, list[float]] = {
        "pr_auc": [],
        "roc_auc": [],
        "precision": [],
        "recall": [],
        "f1": [],
        "brier": [],
        "log_loss": [],
    }

    for _ in range(n_resamples):
        sample = np.concatenate(
            [
                rng.choice(positive, size=len(positive), replace=True),
                rng.choice(negative, size=len(negative), replace=True),
            ]
        )
        sample_target = target[sample]
        sample_probability = probability[sample]
        predicted = (sample_probability >= threshold).astype(int)
        values["pr_auc"].append(float(average_precision_score(sample_target, sample_probability)))
        values["roc_auc"].append(float(roc_auc_score(sample_target, sample_probability)))
        values["precision"].append(
            float(precision_score(sample_target, predicted, zero_division=0))
        )
        values["recall"].append(float(recall_score(sample_target, predicted, zero_division=0)))
        values["f1"].append(float(f1_score(sample_target, predicted, zero_division=0)))
        values["brier"].append(float(brier_score_loss(sample_target, sample_probability)))
        values["log_loss"].append(float(log_loss(sample_target, sample_probability, labels=[0, 1])))

    return {
        metric: (
            float(np.percentile(scores, 2.5)),
            float(np.percentile(scores, 97.5)),
        )
        for metric, scores in values.items()
    }


def calibration_table(
    y_true: ArrayLike,
    y_prob: ArrayLike,
    *,
    bins: int = 10,
) -> pd.DataFrame:
    """Return a quantile-binned calibration table."""

    target, probability = _as_arrays(y_true, y_prob)
    frame = pd.DataFrame({"target": target, "probability": probability})
    frame["bin"] = pd.qcut(frame["probability"], q=bins, duplicates="drop")
    table = (
        frame.groupby("bin", observed=True)
        .agg(
            n=("target", "size"),
            mean_predicted=("probability", "mean"),
            observed_rate=("target", "mean"),
        )
        .reset_index()
    )
    table["gap"] = table["observed_rate"] - table["mean_predicted"]
    return table


def permutation_importance_table(
    model: Pipeline,
    features: pd.DataFrame,
    target: ArrayLike,
    *,
    n_repeats: int = 10,
    random_state: int = 42,
) -> pd.DataFrame:
    """Return permutation importance ranked by mean PR-AUC drop."""

    result = permutation_importance(
        model,
        features,
        target,
        scoring="average_precision",
        n_repeats=n_repeats,
        random_state=random_state,
        n_jobs=-1,
    )
    return (
        pd.DataFrame(
            {
                "feature": features.columns,
                "importance_mean": result.importances_mean,
                "importance_std": result.importances_std,
            }
        )
        .sort_values("importance_mean", ascending=False)
        .reset_index(drop=True)
    )


def positive_probabilities(model: Any, features: pd.DataFrame) -> NDArray[np.float64]:
    """Return positive-class probabilities from a fitted classifier."""

    probabilities = model.predict_proba(features)
    return np.asarray(probabilities[:, 1], dtype=float)
