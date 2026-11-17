"""Training orchestration for current-relationship churn models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.model_selection import (
    GridSearchCV,
    RandomizedSearchCV,
    StratifiedKFold,
    cross_val_predict,
    cross_validate,
)
from sklearn.pipeline import Pipeline

from cronus.modeling.evaluation import positive_probabilities
from cronus.modeling.features import (
    RANDOM_STATE,
    feature_columns,
    make_xy,
)
from cronus.modeling.pipelines import (
    build_logistic_pipeline,
    build_tree_pipeline,
    logistic_param_grid,
    tree_param_distributions,
)

ModelName = Literal["logistic", "tree"]


@dataclass(frozen=True)
class CrossValidationSummary:
    """Aggregated cross-validation metrics."""

    pr_auc_mean: float
    pr_auc_std: float
    roc_auc_mean: float
    roc_auc_std: float
    brier_mean: float
    brier_std: float
    log_loss_mean: float
    log_loss_std: float
    fold_scores: pd.DataFrame


@dataclass(frozen=True)
class TunedModel:
    """A fitted search result and its cross-validation summary."""

    name: str
    estimator: Pipeline
    best_params: dict[str, Any]
    cv: CrossValidationSummary
    include_relationship_count: bool


@dataclass(frozen=True)
class FittedModel:
    """A fitted pipeline with its feature and threshold metadata."""

    pipeline: Pipeline
    features: tuple[str, ...]
    model_name: str
    threshold: float
    include_relationship_count: bool

    def predict_proba(self, frame: pd.DataFrame) -> NDArray[np.float64]:
        return predict_churn(self, frame)


def cross_validate_model(
    estimator: Pipeline,
    features: pd.DataFrame,
    target: pd.Series,
    *,
    cv: int = 5,
    random_state: int = RANDOM_STATE,
) -> CrossValidationSummary:
    """Run stratified cross-validation and return mean and standard deviation."""

    splitter = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    scores = cross_validate(
        estimator,
        features,
        target,
        cv=splitter,
        scoring={
            "pr_auc": "average_precision",
            "roc_auc": "roc_auc",
            "brier": "neg_brier_score",
            "log_loss": "neg_log_loss",
        },
        error_score="raise",
    )
    fold_scores = pd.DataFrame(
        {
            "fold": np.arange(1, cv + 1),
            "pr_auc": scores["test_pr_auc"],
            "roc_auc": scores["test_roc_auc"],
            "brier": -scores["test_brier"],
            "log_loss": -scores["test_log_loss"],
        }
    )
    return CrossValidationSummary(
        pr_auc_mean=float(fold_scores["pr_auc"].mean()),
        pr_auc_std=float(fold_scores["pr_auc"].std()),
        roc_auc_mean=float(fold_scores["roc_auc"].mean()),
        roc_auc_std=float(fold_scores["roc_auc"].std()),
        brier_mean=float(fold_scores["brier"].mean()),
        brier_std=float(fold_scores["brier"].std()),
        log_loss_mean=float(fold_scores["log_loss"].mean()),
        log_loss_std=float(fold_scores["log_loss"].std()),
        fold_scores=fold_scores,
    )


def out_of_fold_probabilities(
    estimator: Pipeline,
    features: pd.DataFrame,
    target: pd.Series,
    *,
    cv: int = 5,
    random_state: int = RANDOM_STATE,
) -> NDArray[np.float64]:
    """Return out-of-fold positive-class probabilities for threshold selection."""

    splitter = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    probabilities = cross_val_predict(
        estimator,
        features,
        target,
        cv=splitter,
        method="predict_proba",
        n_jobs=-1,
    )
    return np.asarray(probabilities[:, 1], dtype=float)


def tune_logistic(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    include_relationship_count: bool = True,
    cv: int = 5,
    random_state: int = RANDOM_STATE,
) -> TunedModel:
    """Tune the logistic-regression baseline with a bounded grid."""

    splitter = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    search = GridSearchCV(
        build_logistic_pipeline(
            include_relationship_count=include_relationship_count,
        ),
        logistic_param_grid(),
        scoring="average_precision",
        cv=splitter,
        refit=True,
        error_score="raise",
        n_jobs=-1,
    )
    search.fit(features, target)
    summary = cross_validate_model(
        search.best_estimator_,
        features,
        target,
        cv=cv,
        random_state=random_state,
    )
    return TunedModel(
        name="logistic",
        estimator=search.best_estimator_,
        best_params=dict(search.best_params_),
        cv=summary,
        include_relationship_count=include_relationship_count,
    )


def tune_tree(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    include_relationship_count: bool = True,
    cv: int = 5,
    n_iter: int = 20,
    random_state: int = RANDOM_STATE,
) -> TunedModel:
    """Tune the gradient-boosted tree with a bounded randomized search."""

    splitter = StratifiedKFold(n_splits=cv, shuffle=True, random_state=random_state)
    search = RandomizedSearchCV(
        build_tree_pipeline(
            include_relationship_count=include_relationship_count,
        ),
        tree_param_distributions(),
        n_iter=n_iter,
        scoring="average_precision",
        cv=splitter,
        refit=True,
        error_score="raise",
        random_state=random_state,
        n_jobs=-1,
    )
    search.fit(features, target)
    summary = cross_validate_model(
        search.best_estimator_,
        features,
        target,
        cv=cv,
        random_state=random_state,
    )
    return TunedModel(
        name="tree",
        estimator=search.best_estimator_,
        best_params=dict(search.best_params_),
        cv=summary,
        include_relationship_count=include_relationship_count,
    )


def fit_final_model(
    frame: pd.DataFrame,
    *,
    model_name: ModelName,
    include_relationship_count: bool = True,
    params: Mapping[str, Any] | None = None,
    threshold: float = 0.5,
) -> FittedModel:
    """Fit a fresh pipeline on the complete current-relationship frame."""

    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1")

    features, target = make_xy(
        frame,
        include_relationship_count=include_relationship_count,
    )
    if model_name == "logistic":
        pipeline = build_logistic_pipeline(
            include_relationship_count=include_relationship_count,
        )
    elif model_name == "tree":
        pipeline = build_tree_pipeline(
            include_relationship_count=include_relationship_count,
        )
    else:
        raise ValueError(f"Unknown model name: {model_name}")

    if params:
        pipeline.set_params(**dict(params))
    pipeline.fit(features, target)

    return FittedModel(
        pipeline=pipeline,
        features=feature_columns(include_relationship_count=include_relationship_count),
        model_name=model_name,
        threshold=threshold,
        include_relationship_count=include_relationship_count,
    )


def predict_churn(model: FittedModel, frame: pd.DataFrame) -> NDArray[np.float64]:
    """Return positive-class churn probabilities for current relationships."""

    missing_columns = [column for column in model.features if column not in frame]
    if missing_columns:
        raise ValueError(f"Missing prediction columns: {', '.join(missing_columns)}")
    features = frame.loc[:, list(model.features)]
    if features.isna().any().any():
        raise ValueError("The prediction frame contains missing feature values")
    return positive_probabilities(model.pipeline, features)
