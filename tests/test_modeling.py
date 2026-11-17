"""Current-relationship modelling contract tests (no database)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cronus.modeling import (
    CURRENT_FEATURES,
    EXCLUDED_FEATURES,
    TARGET_COLUMN,
    bootstrap_intervals,
    build_logistic_pipeline,
    build_preprocessor,
    calibration_table,
    evaluate_predictions,
    feature_columns,
    fit_final_model,
    make_xy,
    out_of_fold_probabilities,
    predict_churn,
    prepare_current_frame,
    select_threshold,
    split_current,
    temporal_split,
    threshold_table,
)
from cronus.schemas import ValidationReport


def _current_frame(baseline: tuple[ValidationReport, pd.DataFrame]) -> pd.DataFrame:
    _, relationships = baseline
    return prepare_current_frame(relationships)


def test_current_frame_contract(baseline: tuple[ValidationReport, pd.DataFrame]) -> None:
    current = _current_frame(baseline)
    assert len(current) == 8_860
    assert int(current["churn"].sum()) == 847
    assert round(100 * current["churn"].mean(), 2) == 9.56
    assert current["customer_id"].is_unique
    assert current["is_latest_relationship"].all()
    assert not current.isna().any().any()


def test_feature_contract_excludes_identifiers() -> None:
    assert not set(CURRENT_FEATURES) & set(EXCLUDED_FEATURES)
    assert TARGET_COLUMN not in CURRENT_FEATURES
    assert "relationship_count" in CURRENT_FEATURES
    assert "relationship_count" not in feature_columns(include_relationship_count=False)


def test_split_is_reproducible_and_stratified(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    first = split_current(current)
    second = split_current(current)
    assert first.train["customer_id"].tolist() == second.train["customer_id"].tolist()
    assert first.test["customer_id"].tolist() == second.test["customer_id"].tolist()
    assert not set(first.train["customer_id"]) & set(first.test["customer_id"])
    assert len(first.train) + len(first.test) == len(current)
    assert abs(first.train["churn"].mean() - current["churn"].mean()) < 0.01


def test_make_xy_without_relationship_count(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    features, target = make_xy(current, include_relationship_count=False)
    assert features.shape == (8_860, 10)
    assert "relationship_count" not in features.columns
    assert target.name == TARGET_COLUMN
    assert target.sum() == 847


def test_prepare_current_frame_rejects_duplicate_customers(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    _, relationships = baseline
    duplicated = pd.concat(
        [relationships.loc[relationships["is_latest_relationship"]].head(2)] * 2,
        ignore_index=True,
    )
    with pytest.raises(ValueError, match="duplicate customers"):
        prepare_current_frame(duplicated)


def test_preprocessor_handles_unseen_categories() -> None:
    frame = pd.DataFrame(
        {
            "telecom_partner": ["Airtel"] * 30 + ["BSNL"] * 30,
            "gender": ["M", "F"] * 30,
            "age": np.arange(20, 80),
            "state": ["Delhi"] * 30 + ["Kerala"] * 30,
            "num_dependents": [0, 1, 2] * 20,
            "estimated_salary": np.linspace(20_000, 80_000, 60),
            "calls_made": np.linspace(1, 100, 60),
            "sms_sent": np.linspace(1, 80, 60),
            "data_used": np.linspace(0, 50, 60),
            "tenure_days": np.linspace(30, 900, 60),
            "churn": [0] * 50 + [1] * 10,
        }
    )
    features, target = make_xy(frame, include_relationship_count=False)
    pipeline = build_logistic_pipeline(include_relationship_count=False)
    pipeline.fit(features, target)

    unseen = frame.head(3).copy()
    unseen.loc[:, "telecom_partner"] = "New Provider"
    unseen.loc[:, "state"] = "New State"
    probabilities = pipeline.predict_proba(unseen.loc[:, list(features.columns)])[:, 1]
    assert np.isfinite(probabilities).all()
    assert ((probabilities >= 0) & (probabilities <= 1)).all()


def test_preprocessor_has_expected_transformers() -> None:
    preprocessor = build_preprocessor(scale_numeric=True, include_relationship_count=False)
    assert preprocessor is not None
    assert len(preprocessor.transformers) == 2


def test_evaluate_predictions_ranges() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.linspace(0.01, 0.99, 100)
    summary = evaluate_predictions(target, probability, threshold=0.5)
    assert 0 <= summary.pr_auc <= 1
    assert 0 <= summary.roc_auc <= 1
    assert 0 <= summary.precision <= 1
    assert 0 <= summary.recall <= 1
    assert 0 <= summary.f1 <= 1
    assert 0 <= summary.brier <= 1
    assert summary.true_negative + summary.false_positive + summary.false_negative == 80
    assert summary.true_positive + summary.false_negative == 20


def test_select_threshold_maximises_f1() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.array([0.1] * 80 + [0.9] * 20)
    threshold = select_threshold(target, probability)
    summary = evaluate_predictions(target, probability, threshold=threshold)
    assert threshold > 0.1
    assert summary.precision == 1.0
    assert summary.recall == 1.0
    assert summary.f1 == 1.0


def test_select_threshold_respects_recall_floor() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.linspace(0.01, 0.99, 100)
    threshold = select_threshold(target, probability, min_recall=0.7)
    summary = evaluate_predictions(target, probability, threshold=threshold)
    assert summary.recall >= 0.7


def test_threshold_table_has_expected_columns() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.linspace(0.01, 0.99, 100)
    table = threshold_table(target, probability)
    assert list(table.columns) == [
        "threshold",
        "predicted_positive",
        "precision",
        "recall",
        "f1",
    ]
    assert len(table) == 19
    assert table["predicted_positive"].is_monotonic_decreasing


def test_bootstrap_intervals_are_ordered() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.linspace(0.01, 0.99, 100)
    intervals = bootstrap_intervals(
        target,
        probability,
        threshold=0.5,
        n_resamples=20,
        random_state=42,
    )
    assert set(intervals) == {"pr_auc", "roc_auc", "precision", "recall", "f1", "brier", "log_loss"}
    for low, high in intervals.values():
        assert low <= high


def test_calibration_table_covers_all_rows() -> None:
    target = np.array([0] * 80 + [1] * 20)
    probability = np.linspace(0.01, 0.99, 100)
    table = calibration_table(target, probability, bins=10)
    assert int(table["n"].sum()) == 100
    assert {"mean_predicted", "observed_rate", "gap"}.issubset(table.columns)


def test_temporal_split_uses_registration_years(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    split = temporal_split(current)
    train_years = pd.to_datetime(split.train["date_of_registration"]).dt.year
    test_years = pd.to_datetime(split.test["date_of_registration"]).dt.year
    assert set(train_years) <= {2020, 2021}
    assert set(test_years) <= {2022, 2023}
    assert set(train_years) & set(test_years) == set()


def test_fit_final_model_and_predict(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    model = fit_final_model(
        current,
        model_name="logistic",
        include_relationship_count=False,
        params={"classifier__C": 0.1},
        threshold=0.18,
    )
    probabilities = predict_churn(model, current.head(25))
    assert probabilities.shape == (25,)
    assert np.isfinite(probabilities).all()
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    assert model.threshold == 0.18
    assert len(model.features) == 10

    incomplete = current.head(5).drop(columns=["calls_made"])
    with pytest.raises(ValueError, match="Missing prediction columns"):
        predict_churn(model, incomplete)


def test_out_of_fold_probabilities_shape(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    features, target = make_xy(current.head(500), include_relationship_count=False)
    pipeline = build_logistic_pipeline(include_relationship_count=False)
    pipeline.fit(features, target)
    probabilities = out_of_fold_probabilities(pipeline, features, target, cv=3)
    assert probabilities.shape == (len(features),)
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
