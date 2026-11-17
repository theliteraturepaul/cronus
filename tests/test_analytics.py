"""Descriptive analytics contract tests (no database)."""

from __future__ import annotations

import pandas as pd
import pytest

from cronus.analytics import (
    AGE_BANDS,
    TENURE_BANDS,
    age_band_table,
    assign_tenure_band,
    assign_usage_quartile,
    churn_rate_table,
    filter_current_frame,
    registration_cohort_table,
    spearman_correlation_table,
    tenure_band_table,
    usage_quartile_table,
    wilson_interval,
)
from cronus.modeling import prepare_current_frame
from cronus.schemas import ValidationReport


def _current_frame(baseline: tuple[ValidationReport, pd.DataFrame]) -> pd.DataFrame:
    _, relationships = baseline
    return prepare_current_frame(relationships)


def test_wilson_interval_is_bounded() -> None:
    low, high = wilson_interval(10, 100)
    assert 0.0 <= low <= 0.1 <= high <= 1.0


def test_wilson_interval_handles_no_rows() -> None:
    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_wilson_interval_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError):
        wilson_interval(5, 4)


def test_churn_rate_table_covers_every_row(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    table = churn_rate_table(current, "telecom_partner", min_n=30)
    assert int(table["n"].sum()) == 8_860
    assert int(table["churned"].sum()) == 847
    assert table["share"].sum() == pytest.approx(1.0)
    assert table["rate"].between(0, 1).all()
    assert table["ci_low"].le(table["rate"]).all()
    assert table["ci_high"].ge(table["rate"]).all()
    assert table["small_sample"].dtype == bool


def test_churn_rate_table_supports_multiple_grouping_columns(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    table = churn_rate_table(current, ["telecom_partner", "gender"])
    assert int(table["n"].sum()) == 8_860
    assert table["segment"].str.contains(" / ").all()


def test_tenure_bands_cover_every_row_exactly_once(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    assigned = assign_tenure_band(current)
    assert len(assigned) == 8_860
    assert assigned["tenure_band"].notna().all()
    table = tenure_band_table(current)
    assert table["segment"].tolist() == list(TENURE_BANDS)
    assert int(table["n"].sum()) == 8_860
    assert int(table["churned"].sum()) == 847


def test_age_bands_cover_every_row_exactly_once(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    table = age_band_table(current)
    assert table["segment"].tolist() == list(AGE_BANDS)
    assert int(table["n"].sum()) == 8_860
    assert int(table["churned"].sum()) == 847


@pytest.mark.parametrize("column", ["calls_made", "sms_sent", "data_used"])
def test_usage_quartiles_cover_every_row(
    baseline: tuple[ValidationReport, pd.DataFrame],
    column: str,
) -> None:
    current = _current_frame(baseline)
    assigned = assign_usage_quartile(current, column)
    assert assigned["usage_quartile"].notna().all()
    table = usage_quartile_table(current, column)
    assert int(table["n"].sum()) == 8_860
    assert int(table["churned"].sum()) == 847
    assert table["min_value"].le(table["max_value"]).all()
    assert table["segment"].iloc[0] == "Q1"


def test_spearman_table_is_descriptive(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    table = spearman_correlation_table(current)
    assert len(table) == 7
    assert table["correlation"].between(-1, 1).all()
    assert table["n"].eq(8_860).all()


def test_registration_cohorts_cover_every_row(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    table = registration_cohort_table(current)
    assert int(table["n"].sum()) == 8_860
    assert table["segment"].tolist() == sorted(table["segment"].tolist())


def test_filter_current_frame_preserves_current_grain(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    filtered = filter_current_frame(current, providers=["BSNL"], age_range=(20, 60))
    assert not filtered.empty
    assert set(filtered["telecom_partner"]) == {"BSNL"}
    assert filtered["age"].between(20, 60).all()
    assert filtered["customer_id"].is_unique
    assert filtered["is_latest_relationship"].all()


def test_filter_rejects_inverted_ranges(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    with pytest.raises(ValueError, match="minimum"):
        filter_current_frame(current, age_range=(60, 20))


def test_analytics_reject_duplicate_current_customers(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    duplicated = pd.concat([current.head(2), current.head(2)], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate customer"):
        churn_rate_table(duplicated, "telecom_partner")


def test_analytics_reject_historical_rows(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    historical = current.copy(deep=True)
    historical.loc[0, "is_latest_relationship"] = False
    with pytest.raises(ValueError, match="historical"):
        churn_rate_table(historical, "telecom_partner")


def test_analytics_reject_missing_columns(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    with pytest.raises(ValueError, match="Missing analytics columns"):
        tenure_band_table(current.drop(columns=["tenure_days"]))


def test_analytics_do_not_mutate_the_input(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    current = _current_frame(baseline)
    before = current.copy(deep=True)
    churn_rate_table(current, "telecom_partner")
    tenure_band_table(current)
    usage_quartile_table(current, "calls_made")
    registration_cohort_table(current)
    filter_current_frame(current, providers=["BSNL"])
    pd.testing.assert_frame_equal(current, before)
