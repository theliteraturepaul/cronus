"""Final-model serving contract tests (no database)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cronus.modeling import fit_final_model, predict_churn, prepare_current_frame
from cronus.modeling.serving import (
    DEFAULT_THRESHOLD_POLICY,
    FINAL_INCLUDE_RELATIONSHIP_COUNT,
    FINAL_MODEL_NAME,
    FINAL_MODEL_PARAMS,
    FINAL_THRESHOLD,
    HIGH_RECALL_THRESHOLD,
    MODEL_CARD,
    THRESHOLD_POLICIES,
    ScoreSummary,
    ScoringModel,
    fit_scoring_model,
    score_current_relationships,
    summarize_scores,
)
from cronus.schemas import ValidationReport


def _current_frame(baseline: tuple[ValidationReport, pd.DataFrame]) -> pd.DataFrame:
    _, relationships = baseline
    return prepare_current_frame(relationships)


@pytest.fixture(scope="module")
def current(baseline: tuple[ValidationReport, pd.DataFrame]) -> pd.DataFrame:
    return _current_frame(baseline)


@pytest.fixture(scope="module")
def scoring(current: pd.DataFrame) -> ScoringModel:
    return fit_scoring_model(current, dataset_id="baseline")


def test_final_constants_match_baseline() -> None:
    assert FINAL_MODEL_NAME == "logistic"
    assert FINAL_INCLUDE_RELATIONSHIP_COUNT is False
    assert FINAL_MODEL_PARAMS == {"classifier__C": 0.1}
    assert FINAL_THRESHOLD == 0.1840
    assert HIGH_RECALL_THRESHOLD == 0.0981
    assert MODEL_CARD.feature_count == 10
    assert MODEL_CARD.baseline_rows == 8_860
    assert MODEL_CARD.baseline_events == 847
    assert MODEL_CARD.baseline_prevalence == 0.0956


def test_threshold_policies_are_fixed() -> None:
    assert len(THRESHOLD_POLICIES) == 2
    assert DEFAULT_THRESHOLD_POLICY.key == "max_f1"
    assert DEFAULT_THRESHOLD_POLICY.threshold == FINAL_THRESHOLD
    assert [policy.threshold for policy in THRESHOLD_POLICIES] == [
        FINAL_THRESHOLD,
        HIGH_RECALL_THRESHOLD,
    ]


def test_fit_scoring_model_uses_the_full_current_frame(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    assert scoring.current_rows == 8_860
    assert scoring.threshold == 0.1840
    assert scoring.dataset_id == "baseline"
    assert len(scoring.model.features) == 10
    assert scoring.fitted_at.tzinfo is not None
    assert current["customer_id"].is_unique


def test_fit_scoring_model_rejects_an_empty_frame() -> None:
    empty = pd.DataFrame(columns=["customer_id", "is_latest_relationship", "churn"])
    with pytest.raises(ValueError):
        fit_scoring_model(empty, dataset_id="empty")


def test_scores_cover_every_current_relationship(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    scored = score_current_relationships(scoring, current)
    assert len(scored) == 8_860
    assert scored["customer_id"].is_unique
    assert np.isfinite(scored["churn_probability"]).all()
    assert scored["churn_probability"].between(0, 1).all()
    assert scored["predicted_churn"].dtype == bool
    assert scored["threshold"].eq(0.1840).all()
    assert "churn" not in scored.columns
    assert scored["score_rank"].tolist() == list(range(1, 8_861))


def test_predicted_flag_matches_the_threshold(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    scored = score_current_relationships(scoring, current)
    expected = scored["churn_probability"] >= 0.1840
    pd.testing.assert_series_equal(
        scored["predicted_churn"].reset_index(drop=True),
        expected.reset_index(drop=True),
        check_names=False,
    )


def test_review_priority_bands(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    scored = score_current_relationships(scoring, current)
    probability = scored["churn_probability"]
    priority = scored["review_priority"]
    assert (priority[probability >= 0.1840] == "High").all()
    elevated = (probability >= 0.092) & (probability < 0.1840)
    assert (priority[elevated] == "Elevated").all()
    assert (priority[probability < 0.092] == "Low").all()


def test_threshold_changes_flags_but_not_probabilities(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    default_scores = score_current_relationships(scoring, current)
    wide_scores = score_current_relationships(scoring, current, threshold=0.5)
    pd.testing.assert_series_equal(
        default_scores["churn_probability"],
        wide_scores["churn_probability"],
        check_names=False,
    )
    assert wide_scores["predicted_churn"].sum() <= default_scores["predicted_churn"].sum()
    assert wide_scores["threshold"].eq(0.5).all()


def test_score_rejects_an_invalid_threshold(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    with pytest.raises(ValueError, match="threshold"):
        score_current_relationships(scoring, current, threshold=1.1)


def test_score_rejects_a_missing_model_feature(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    with pytest.raises(ValueError, match="Missing prediction columns"):
        score_current_relationships(scoring, current.drop(columns=["estimated_salary"]))


def test_score_does_not_mutate_the_input(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    before = current.copy(deep=True)
    score_current_relationships(scoring, current)
    pd.testing.assert_frame_equal(current, before)


def test_summarize_scores_matches_the_scored_frame(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    scored = score_current_relationships(scoring, current)
    summary = summarize_scores(scored)
    assert isinstance(summary, ScoreSummary)
    assert summary.scored_rows == 8_860
    assert summary.flagged_count == int(scored["predicted_churn"].sum())
    assert summary.flagged_rate == pytest.approx(summary.flagged_count / 8_860)
    assert summary.high_priority_count == int((scored["review_priority"] == "High").sum())
    assert 0 <= summary.mean_probability <= 1
    assert 0 <= summary.median_probability <= 1


def test_summarize_scores_rejects_an_empty_frame() -> None:
    with pytest.raises(ValueError, match="empty"):
        summarize_scores(pd.DataFrame())


def test_predict_churn_rejects_missing_features(
    current: pd.DataFrame,
    scoring: ScoringModel,
) -> None:
    with pytest.raises(ValueError, match="Missing prediction columns"):
        predict_churn(scoring.model, current.drop(columns=["calls_made"]))


def test_final_fit_api_remains_reusable(current: pd.DataFrame) -> None:
    model = fit_final_model(
        current,
        model_name="logistic",
        include_relationship_count=False,
        params={"classifier__C": 0.1},
        threshold=0.1840,
    )
    probabilities = predict_churn(model, current.head(10))
    assert probabilities.shape == (10,)
    assert len(model.features) == 10
