"""Feature contract and data preparation for current-relationship churn models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

from cronus.schemas import ValidationReport
from cronus.validation import validate_csv

RANDOM_STATE = 42
TARGET_COLUMN = "churn"

CATEGORICAL_FEATURES: tuple[str, ...] = (
    "telecom_partner",
    "gender",
    "state",
)

NUMERIC_FEATURES: tuple[str, ...] = (
    "age",
    "num_dependents",
    "estimated_salary",
    "calls_made",
    "sms_sent",
    "data_used",
    "tenure_days",
    "relationship_count",
)

CURRENT_FEATURES: tuple[str, ...] = (
    "telecom_partner",
    "gender",
    "age",
    "state",
    "num_dependents",
    "estimated_salary",
    "calls_made",
    "sms_sent",
    "data_used",
    "tenure_days",
    "relationship_count",
)

EXCLUDED_FEATURES: tuple[str, ...] = (
    "customer_id",
    "pincode",
    "city",
    "record_id",
    "dataset_id",
    "source_row_number",
    "is_latest_relationship",
    "relationship_seq",
    "date_of_registration",
    "created_at",
)

REQUIRED_COLUMNS: tuple[str, ...] = (
    "customer_id",
    "is_latest_relationship",
    *CURRENT_FEATURES,
    TARGET_COLUMN,
)

OPTIONAL_FEATURES: tuple[str, ...] = ("relationship_count",)


@dataclass(frozen=True)
class DatasetSplit:
    """A reproducible train/test split of the current-relationship frame."""

    train: pd.DataFrame
    test: pd.DataFrame


def feature_columns(*, include_relationship_count: bool = True) -> tuple[str, ...]:
    """Return the model feature columns in the documented order."""

    if include_relationship_count:
        return CURRENT_FEATURES
    return tuple(feature for feature in CURRENT_FEATURES if feature != "relationship_count")


def prepare_current_frame(relationships: pd.DataFrame) -> pd.DataFrame:
    """Return one latest relationship per customer with validated columns.

    The function never deduplicates rows.  Duplicate customer IDs on the latest
    grain indicate an invalid input and raise ``ValueError``.
    """

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in relationships.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    latest = relationships["is_latest_relationship"].astype(bool)
    current = relationships.loc[latest].copy().reset_index(drop=True)
    if current.empty:
        raise ValueError("The relationships frame has no latest relationships")

    if current["customer_id"].duplicated().any():
        duplicates = int(current["customer_id"].duplicated().sum())
        raise ValueError(f"The latest-relationship frame contains {duplicates} duplicate customers")

    if current[[*CURRENT_FEATURES, TARGET_COLUMN]].isna().any().any():
        raise ValueError("The current-relationship frame contains missing model values")

    if not current[TARGET_COLUMN].isin([0, 1, False, True]).all():
        raise ValueError("The churn column must contain only 0 or 1")

    current[TARGET_COLUMN] = current[TARGET_COLUMN].astype(int)
    return current


def load_current_frame(csv_path: Path) -> tuple[ValidationReport, pd.DataFrame]:
    """Validate a CSV, then return its report and current-relationship frame."""

    report, relationships = validate_csv(csv_path)
    if report.error_count:
        raise ValueError(f"The CSV has {report.error_count} validation errors")
    return report, prepare_current_frame(relationships)


def make_xy(
    frame: pd.DataFrame,
    *,
    include_relationship_count: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Split a current-relationship frame into model features and target."""

    features = feature_columns(include_relationship_count=include_relationship_count)
    missing_columns = [column for column in (*features, TARGET_COLUMN) if column not in frame]
    if missing_columns:
        raise ValueError(f"Missing model columns: {', '.join(missing_columns)}")

    features_frame = frame.loc[:, list(features)].copy()
    target = frame.loc[:, TARGET_COLUMN].astype(int).copy()
    return features_frame, target


def split_current(
    frame: pd.DataFrame,
    *,
    test_size: float = 0.2,
    random_state: int = RANDOM_STATE,
) -> DatasetSplit:
    """Create a stratified train/test split of the current-relationship frame."""

    train, test = train_test_split(
        frame,
        test_size=test_size,
        stratify=frame[TARGET_COLUMN],
        random_state=random_state,
    )
    return DatasetSplit(
        train=train.reset_index(drop=True),
        test=test.reset_index(drop=True),
    )


def temporal_split(
    frame: pd.DataFrame,
    *,
    train_years: tuple[int, ...] = (2020, 2021),
    test_years: tuple[int, ...] = (2022, 2023),
) -> DatasetSplit:
    """Split current relationships by registration year for a temporal check."""

    years = pd.to_datetime(frame["date_of_registration"]).dt.year
    train = frame.loc[years.isin(train_years)].reset_index(drop=True)
    test = frame.loc[years.isin(test_years)].reset_index(drop=True)
    if train.empty or test.empty:
        raise ValueError("The temporal split produced an empty train or test frame")
    return DatasetSplit(train=train, test=test)
