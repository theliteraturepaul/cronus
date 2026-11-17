"""Descriptive analytics helpers for current customer-provider relationships."""

from __future__ import annotations

import math
from collections.abc import Sequence

import pandas as pd

TENURE_BANDS: tuple[str, ...] = (
    "0–90 days",
    "91–180 days",
    "181–365 days",
    "366–730 days",
    "731+ days",
)

_TENURE_BINS: tuple[float, ...] = (-1, 90, 180, 365, 730, math.inf)

AGE_BANDS: tuple[str, ...] = (
    "15–24",
    "25–34",
    "35–44",
    "45–54",
    "55–64",
    "65+",
)

_AGE_BINS: tuple[float, ...] = (14, 24, 34, 44, 54, 64, 100)


def _assert_current_grain(frame: pd.DataFrame) -> None:
    required = {"customer_id", "is_latest_relationship"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing current-grain columns: {', '.join(missing)}")
    if frame.empty:
        raise ValueError("The current-relationship frame is empty")
    if not frame["is_latest_relationship"].astype(bool).all():
        raise ValueError("The frame contains historical relationships")
    if frame["customer_id"].duplicated().any():
        duplicates = int(frame["customer_id"].duplicated().sum())
        raise ValueError(
            f"The current-relationship frame contains {duplicates} duplicate customer(s)"
        )


def _require_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing analytics columns: {', '.join(missing)}")


def wilson_interval(
    successes: int,
    total: int,
    z: float = 1.959963984540054,
) -> tuple[float, float]:
    """Return a Wilson score interval as proportions in ``[0, 1]``."""

    if total < 0 or successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")
    if total == 0:
        return (0.0, 0.0)

    proportion = successes / total
    denominator = 1.0 + (z * z / total)
    centre = (proportion + (z * z / (2.0 * total))) / denominator
    margin = (
        z
        * math.sqrt((proportion * (1.0 - proportion) / total) + (z * z / (4.0 * total * total)))
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _summarise_groups(
    frame: pd.DataFrame,
    group_columns: Sequence[str],
    *,
    order: Sequence[str] | None = None,
    min_n: int = 0,
) -> pd.DataFrame:
    if min_n < 0:
        raise ValueError("min_n must not be negative")
    _require_columns(frame, [*group_columns, "churn"])
    if frame["churn"].isna().any():
        raise ValueError("The churn column contains missing values")

    working = frame.copy(deep=True)
    for column in group_columns:
        if working[column].isna().any():
            raise ValueError(f"The grouping column {column!r} contains missing values")

    grouped = (
        working.groupby(list(group_columns), observed=True, sort=False, dropna=False)
        .agg(n=("churn", "size"), churned=("churn", "sum"))
        .reset_index()
    )
    grouped["churned"] = grouped["churned"].astype("int64")
    grouped["segment"] = grouped[list(group_columns)].astype(str).agg(" / ".join, axis=1)

    total = len(working)
    grouped["rate"] = grouped["churned"].astype(float) / grouped["n"].astype(float)
    intervals = [
        wilson_interval(int(churned), int(n))
        for churned, n in zip(grouped["churned"], grouped["n"], strict=True)
    ]
    grouped["ci_low"] = [interval[0] for interval in intervals]
    grouped["ci_high"] = [interval[1] for interval in intervals]
    grouped["share"] = grouped["n"].astype(float) / total if total else 0.0
    grouped["small_sample"] = grouped["n"].lt(min_n) if min_n > 0 else False

    columns = [
        "segment",
        "n",
        "churned",
        "rate",
        "ci_low",
        "ci_high",
        "share",
        "small_sample",
    ]
    result = grouped.loc[:, columns]

    if order is not None:
        result = (
            result.set_index("segment").reindex(list(order)).rename_axis("segment").reset_index()
        )
        for column in ("n", "churned"):
            result[column] = result[column].fillna(0).astype("int64")
        for column in ("rate", "ci_low", "ci_high", "share"):
            result[column] = result[column].fillna(0.0).astype(float)
        result["small_sample"] = result["small_sample"].fillna(False).astype(bool)
    else:
        result = result.sort_values(
            ["n", "segment"],
            ascending=[False, True],
            kind="stable",
        ).reset_index(drop=True)

    return result


def churn_rate_table(
    frame: pd.DataFrame,
    by: str | Sequence[str],
    *,
    min_n: int = 0,
) -> pd.DataFrame:
    """Return churn counts and Wilson intervals for one or more segments."""

    _assert_current_grain(frame)
    group_columns = [by] if isinstance(by, str) else list(by)
    if not group_columns:
        raise ValueError("At least one grouping column is required")
    return _summarise_groups(frame, group_columns, min_n=min_n)


def assign_tenure_band(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with an ordered ``tenure_band`` column."""

    _assert_current_grain(frame)
    _require_columns(frame, ["tenure_days"])
    if frame["tenure_days"].isna().any():
        raise ValueError("The tenure_days column contains missing values")

    working = frame.copy(deep=True)
    working["tenure_band"] = pd.cut(
        working["tenure_days"],
        bins=list(_TENURE_BINS),
        labels=list(TENURE_BANDS),
        right=True,
        include_lowest=True,
    )
    if working["tenure_band"].isna().any():
        raise ValueError("tenure_days produced an unassigned tenure band")
    working["tenure_band"] = working["tenure_band"].astype(str)
    return working


def tenure_band_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return churn by ordered tenure bands."""

    working = assign_tenure_band(frame)
    return _summarise_groups(
        working,
        ["tenure_band"],
        order=TENURE_BANDS,
    )


def assign_age_band(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with an ordered ``age_band`` column."""

    _assert_current_grain(frame)
    _require_columns(frame, ["age"])
    if frame["age"].isna().any():
        raise ValueError("The age column contains missing values")

    working = frame.copy(deep=True)
    working["age_band"] = pd.cut(
        working["age"],
        bins=list(_AGE_BINS),
        labels=list(AGE_BANDS),
        right=True,
        include_lowest=True,
    )
    if working["age_band"].isna().any():
        raise ValueError("age produced an unassigned age band")
    working["age_band"] = working["age_band"].astype(str)
    return working


def age_band_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return churn by ordered age bands."""

    working = assign_age_band(frame)
    return _summarise_groups(
        working,
        ["age_band"],
        order=AGE_BANDS,
    )


def assign_usage_quartile(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """Return a copy with a ``usage_quartile`` column for one usage metric."""

    _assert_current_grain(frame)
    _require_columns(frame, [column])
    if frame[column].isna().any():
        raise ValueError(f"The usage column {column!r} contains missing values")
    if not pd.api.types.is_numeric_dtype(frame[column]):
        raise ValueError(f"The usage column {column!r} must be numeric")

    working = frame.copy(deep=True)
    quartile = pd.qcut(working[column], q=4, labels=False, duplicates="drop")
    if quartile.isna().any():
        raise ValueError(f"Could not assign quartiles for {column!r}")

    bin_count = int(quartile.max()) + 1
    labels = [f"Q{index + 1}" for index in range(bin_count)]
    working["usage_quartile"] = quartile.astype("int64").map(dict(enumerate(labels)))
    return working


def usage_quartile_table(
    frame: pd.DataFrame,
    column: str,
) -> pd.DataFrame:
    """Return churn by usage quartile for one numeric usage column."""

    working = assign_usage_quartile(frame, column)
    labels = [f"Q{index + 1}" for index in range(working["usage_quartile"].nunique())]
    ranges = (
        working.groupby("usage_quartile", observed=True)[column]
        .agg(min_value="min", max_value="max")
        .reset_index()
    )
    table = _summarise_groups(
        working,
        ["usage_quartile"],
        order=labels,
    ).merge(ranges, left_on="segment", right_on="usage_quartile", how="left")
    table = table.drop(columns=["usage_quartile"])
    return table.loc[
        :,
        [
            "segment",
            "min_value",
            "max_value",
            "n",
            "churned",
            "rate",
            "ci_low",
            "ci_high",
            "share",
            "small_sample",
        ],
    ]


def registration_cohort_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return churn by registration year."""

    _assert_current_grain(frame)
    _require_columns(frame, ["date_of_registration"])
    if frame["date_of_registration"].isna().any():
        raise ValueError("The date_of_registration column contains missing values")

    working = frame.copy(deep=True)
    years = pd.to_datetime(working["date_of_registration"], errors="raise").dt.year
    working["cohort_year"] = years.astype(int)
    order = [str(year) for year in sorted(working["cohort_year"].unique().tolist())]
    return _summarise_groups(
        working,
        ["cohort_year"],
        order=order,
    )


def spearman_correlation_table(
    frame: pd.DataFrame,
    columns: Sequence[str] = (
        "age",
        "num_dependents",
        "estimated_salary",
        "calls_made",
        "sms_sent",
        "data_used",
        "tenure_days",
    ),
) -> pd.DataFrame:
    """Return descriptive Spearman correlations between numeric features and churn."""

    _assert_current_grain(frame)
    _require_columns(frame, ["churn", *columns])
    target = frame["churn"].astype(float)
    rows: list[dict[str, float | int | str]] = []
    for column in columns:
        values = frame[column]
        if values.isna().any():
            raise ValueError(f"The correlation column {column!r} contains missing values")
        if not pd.api.types.is_numeric_dtype(values):
            raise ValueError(f"The correlation column {column!r} must be numeric")
        rows.append(
            {
                "feature": column,
                "correlation": float(values.corr(target, method="spearman")),
                "n": len(values),
            }
        )
    return pd.DataFrame(rows, columns=["feature", "correlation", "n"])


def filter_current_frame(
    frame: pd.DataFrame,
    *,
    providers: Sequence[str] | None = None,
    states: Sequence[str] | None = None,
    genders: Sequence[str] | None = None,
    age_range: tuple[int, int] | None = None,
    tenure_range: tuple[int, int] | None = None,
) -> pd.DataFrame:
    """Return a filtered copy of a current-relationship frame."""

    _assert_current_grain(frame)
    working = frame.copy(deep=True)

    if providers:
        working = working.loc[working["telecom_partner"].isin(list(providers))]
    if states:
        working = working.loc[working["state"].isin(list(states))]
    if genders:
        working = working.loc[working["gender"].isin(list(genders))]
    if age_range is not None:
        low, high = age_range
        if low > high:
            raise ValueError("age_range minimum must not exceed its maximum")
        working = working.loc[working["age"].between(low, high)]
    if tenure_range is not None:
        low, high = tenure_range
        if low > high:
            raise ValueError("tenure_range minimum must not exceed its maximum")
        working = working.loc[working["tenure_days"].between(low, high)]

    return working.reset_index(drop=True)
