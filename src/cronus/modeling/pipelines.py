"""Preprocessing and estimator pipelines for churn modelling."""

from __future__ import annotations

from typing import Any

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from cronus.modeling.features import (
    CATEGORICAL_FEATURES,
    RANDOM_STATE,
    feature_columns,
)


def build_preprocessor(
    *,
    scale_numeric: bool,
    include_relationship_count: bool = True,
) -> ColumnTransformer:
    """Build the shared preprocessing transformer.

    Rare categories are grouped by ``OneHotEncoder``.  Unseen categories are
    ignored at prediction time.  All fitting happens inside the model pipeline.
    """

    features = feature_columns(include_relationship_count=include_relationship_count)
    categorical = [feature for feature in features if feature in CATEGORICAL_FEATURES]
    numeric = [feature for feature in features if feature not in CATEGORICAL_FEATURES]

    return ColumnTransformer(
        transformers=[
            (
                "categorical",
                OneHotEncoder(
                    handle_unknown="ignore",
                    min_frequency=50,
                    sparse_output=False,
                ),
                categorical,
            ),
            (
                "numeric",
                StandardScaler() if scale_numeric else "passthrough",
                numeric,
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def build_logistic_pipeline(
    *,
    include_relationship_count: bool = True,
) -> Pipeline:
    """Return the logistic-regression baseline pipeline."""

    return Pipeline(
        steps=[
            (
                "preprocessor",
                build_preprocessor(
                    scale_numeric=True,
                    include_relationship_count=include_relationship_count,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=2_000,
                    solver="lbfgs",
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def build_tree_pipeline(
    *,
    include_relationship_count: bool = True,
) -> Pipeline:
    """Return the gradient-boosted tree pipeline."""

    return Pipeline(
        steps=[
            (
                "preprocessor",
                build_preprocessor(
                    scale_numeric=False,
                    include_relationship_count=include_relationship_count,
                ),
            ),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    learning_rate=0.05,
                    max_iter=200,
                    max_leaf_nodes=31,
                    min_samples_leaf=30,
                    l2_regularization=1.0,
                    early_stopping=False,
                    random_state=RANDOM_STATE,
                ),
            ),
        ]
    )


def logistic_param_grid() -> dict[str, list[Any]]:
    """Return the bounded logistic-regression search grid."""

    return {
        "classifier__C": [0.01, 0.1, 1.0, 10.0],
        "classifier__class_weight": [None, "balanced"],
    }


def tree_param_distributions() -> dict[str, list[Any]]:
    """Return the bounded tree search space."""

    return {
        "classifier__learning_rate": [0.03, 0.05, 0.1],
        "classifier__max_leaf_nodes": [15, 31],
        "classifier__min_samples_leaf": [20, 40],
        "classifier__l2_regularization": [0.0, 1.0],
    }
