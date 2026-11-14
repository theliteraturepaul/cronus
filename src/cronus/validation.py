"""CSV validation, normalisation and relationship-level derivation."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from cronus.schemas import (
    UploadLimitExceeded,
    ValidationIssue,
    ValidationReport,
)

MAX_ISSUES = 50

REQUIRED_COLUMNS: tuple[str, ...] = (
    "customer_id",
    "telecom_partner",
    "gender",
    "age",
    "state",
    "city",
    "pincode",
    "date_of_registration",
    "num_dependents",
    "estimated_salary",
    "calls_made",
    "sms_sent",
    "data_used",
    "churn",
)

DERIVED_COLUMNS: tuple[str, ...] = (
    "source_row_number",
    "relationship_seq",
    "relationship_count",
    "is_latest_relationship",
    "tenure_days",
)

_PINCODE_RE = re.compile(r"^[0-9]{6}$")
_EXCEL_FLOAT_RE = re.compile(r"^([0-9]+)\.0$")
_DATE_FORMATS = ("%d-%m-%Y", "%Y-%m-%d")


class _IssueCollector:
    """Collect issues while retaining at most ``MAX_ISSUES`` examples."""

    def __init__(self) -> None:
        self.items: list[ValidationIssue] = []
        self.total = 0

    def add(
        self,
        code: str,
        message: str,
        *,
        row_number: int | None = None,
        column: str | None = None,
        value: str | None = None,
    ) -> None:
        self.total += 1
        if len(self.items) < MAX_ISSUES:
            self.items.append(
                ValidationIssue(
                    code=code,
                    message=message,
                    row_number=row_number,
                    column=column,
                    value=value,
                )
            )

    @property
    def truncated(self) -> bool:
        return self.total > MAX_ISSUES


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in REQUIRED_COLUMNS})


def _read_source(source: Path | bytes) -> bytes:
    if isinstance(source, Path):
        return source.read_bytes()
    return bytes(source)


def _parse_date(raw: str) -> date | None:
    value = raw.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _parse_int(raw: str) -> int | None:
    value = raw.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        number = float(value)
    except ValueError:
        return None
    if not number.is_integer():
        return None
    try:
        return int(number)
    except (OverflowError, ValueError):
        return None


def _normalise_gender(raw: str) -> str | None:
    value = raw.strip().lower()
    if value in {"m", "male"}:
        return "M"
    if value in {"f", "female"}:
        return "F"
    return None


def _normalise_pincode(raw: str) -> tuple[str | None, bool, bool]:
    """Return ``(pincode, zero_padded, excel_artifact)``."""

    value = raw.strip()
    excel_artifact = False
    zero_padded = False

    match = _EXCEL_FLOAT_RE.fullmatch(value)
    if match:
        value = match.group(1)
        excel_artifact = True

    if value.isdigit() and len(value) < 6:
        value = value.zfill(6)
        zero_padded = True

    if not _PINCODE_RE.fullmatch(value):
        return None, zero_padded, excel_artifact
    return value, zero_padded, excel_artifact


def _percentage(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator * 100.0 / denominator, 2)


def _empty_relationships() -> pd.DataFrame:
    frame = _empty_frame()
    for column in DERIVED_COLUMNS:
        if column == "is_latest_relationship":
            frame[column] = pd.Series(dtype="bool")
        elif (
            column in {"relationship_seq", "relationship_count", "source_row_number"}
            or column == "tenure_days"
        ):
            frame[column] = pd.Series(dtype="int64")
    return frame


def derive_relationships(relationships: pd.DataFrame, as_of_date: date) -> pd.DataFrame:
    """Add sequence, latest flag and tenure to relationship rows.

    Ordering is ``(customer_id, registration_date, source_row_number)``.  The
    next relationship's registration date is used as the proxy for the switch
    date of a historical relationship.  For the latest relationship the
    snapshot date (``as_of_date``) is the end of observation.
    """

    if "customer_id" not in relationships.columns:
        raise ValueError("relationships must contain a customer_id column")

    if "registration_date" in relationships.columns:
        date_column = "registration_date"
    elif "date_of_registration" in relationships.columns:
        date_column = "date_of_registration"
    else:
        raise ValueError(
            "relationships must contain a registration_date or date_of_registration column"
        )

    if relationships.empty:
        return _empty_relationships()

    working = relationships.copy(deep=True)
    if "source_row_number" not in working.columns:
        working["source_row_number"] = np.arange(1, len(working) + 1)
    working["source_row_number"] = working["source_row_number"].astype(int)

    working = working.sort_values(
        ["customer_id", date_column, "source_row_number"],
        kind="stable",
    ).reset_index(drop=True)

    grouped = working.groupby("customer_id", sort=False)
    working["relationship_seq"] = grouped.cumcount() + 1
    working["relationship_count"] = grouped["customer_id"].transform("size")
    working["is_latest_relationship"] = working["relationship_seq"].eq(
        working["relationship_count"]
    )

    registration = pd.to_datetime(working[date_column])
    next_registration = registration.groupby(working["customer_id"], sort=False).shift(-1)
    latest_tenure = (pd.Timestamp(as_of_date) - registration).dt.days
    historical_tenure = (next_registration - registration).dt.days

    working["tenure_days"] = np.where(
        working["is_latest_relationship"],
        latest_tenure,
        historical_tenure,
    ).astype(int)
    working["relationship_seq"] = working["relationship_seq"].astype(int)
    working["relationship_count"] = working["relationship_count"].astype(int)
    working[date_column] = registration.dt.date
    working["is_latest_relationship"] = working["is_latest_relationship"].astype(bool)

    working = working.sort_values("source_row_number", kind="stable").reset_index(drop=True)
    return working


def _finalise_report(
    report: ValidationReport,
    errors: _IssueCollector,
    warnings: _IssueCollector,
    frame: pd.DataFrame,
) -> tuple[ValidationReport, pd.DataFrame]:
    report.errors = errors.items
    report.warnings = warnings.items
    report.error_count = errors.total
    report.warning_count = warnings.total
    report.errors_truncated = errors.truncated
    report.warnings_truncated = warnings.truncated
    return report, frame


def validate_csv(
    source: Path | bytes,
    *,
    as_of_date: date | None = None,
) -> tuple[ValidationReport, pd.DataFrame]:
    """Validate a churn CSV and return a report plus a cleaned DataFrame.

    The caller's input is never mutated.  Hard errors do not write to the
    database; ingestion refuses to proceed when ``report.has_errors`` is true.
    """

    data = _read_source(source)
    report = ValidationReport()
    errors = _IssueCollector()
    warnings = _IssueCollector()

    if not data.strip():
        errors.add("empty_file", "The uploaded file is empty.")
        return _finalise_report(report, errors, warnings, _empty_frame())

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        errors.add("encoding_error", "The file is not valid UTF-8 text.")
        return _finalise_report(report, errors, warnings, _empty_frame())

    try:
        header_reader = csv.reader(io.StringIO(text))
        raw_header = next(header_reader)
    except (StopIteration, csv.Error):
        errors.add("empty_file", "The uploaded file has no header row.")
        return _finalise_report(report, errors, warnings, _empty_frame())

    normalised_header = [str(column).strip().lower() for column in raw_header]
    report.column_count = len(normalised_header)

    duplicates = [name for name, count in Counter(normalised_header).items() if count > 1]
    if duplicates:
        for name in duplicates:
            errors.add(
                "duplicate_column",
                f"Column {name!r} appears more than once in the header.",
                column=name,
            )
        return _finalise_report(report, errors, warnings, _empty_frame())

    try:
        frame = pd.read_csv(
            io.StringIO(text),
            dtype=str,
            keep_default_na=False,
            sep=",",
        )
    except pd.errors.EmptyDataError:
        errors.add("empty_file", "The uploaded file has no data rows.")
        return _finalise_report(report, errors, warnings, _empty_frame())
    except (pd.errors.ParserError, csv.Error) as exc:
        errors.add("unparseable_csv", f"The CSV could not be parsed: {exc}")
        return _finalise_report(report, errors, warnings, _empty_frame())

    frame.columns = normalised_header
    report.row_count = len(frame)

    extras = [name for name in normalised_header if name not in REQUIRED_COLUMNS]
    for name in extras:
        warnings.add(
            "extra_column",
            f"Extra column {name!r} was ignored.",
            column=name or None,
        )

    missing = [name for name in REQUIRED_COLUMNS if name not in frame.columns]
    if missing:
        for name in missing:
            errors.add(
                "missing_column",
                f"Required column {name!r} is missing.",
                column=name,
            )
        return _finalise_report(report, errors, warnings, frame.copy(deep=True))

    if frame.empty:
        errors.add("empty_dataset", "The CSV contains a header but no data rows.")
        return _finalise_report(report, errors, warnings, _empty_frame())

    records: list[dict[str, Any]] = []
    for row_number, raw_row in enumerate(frame.to_dict(orient="records"), start=1):
        values = {column: str(raw_row[column]).strip() for column in REQUIRED_COLUMNS}

        missing_values = [column for column, value in values.items() if not value]
        if missing_values:
            for column in missing_values:
                errors.add(
                    "missing_value",
                    f"Missing value in required column {column!r}.",
                    row_number=row_number,
                    column=column,
                )
            continue

        row_has_error = False

        customer_id = values["customer_id"]
        telecom_partner = values["telecom_partner"]
        state = values["state"]
        city = values["city"]

        gender = _normalise_gender(values["gender"])
        if gender is None:
            errors.add(
                "invalid_gender",
                "Gender must be M/Male/F/Female.",
                row_number=row_number,
                column="gender",
                value=values["gender"],
            )
            row_has_error = True

        pincode, zero_padded, excel_artifact = _normalise_pincode(values["pincode"])
        if pincode is None:
            errors.add(
                "invalid_pincode",
                "Pincode must contain exactly six digits after normalisation.",
                row_number=row_number,
                column="pincode",
                value=values["pincode"],
            )
            row_has_error = True
        else:
            if excel_artifact:
                warnings.add(
                    "pincode_excel_artifact",
                    "Pincode had an Excel '.0' artifact and was normalised.",
                    row_number=row_number,
                    column="pincode",
                    value=values["pincode"],
                )
            if zero_padded:
                warnings.add(
                    "pincode_zero_padded",
                    "Pincode was zero-padded to six digits.",
                    row_number=row_number,
                    column="pincode",
                    value=values["pincode"],
                )

        registration_date = _parse_date(values["date_of_registration"])
        if registration_date is None:
            errors.add(
                "invalid_date",
                "Registration date must use DD-MM-YYYY or YYYY-MM-DD.",
                row_number=row_number,
                column="date_of_registration",
                value=values["date_of_registration"],
            )
            row_has_error = True

        numbers: dict[str, int] = {}
        for column in (
            "age",
            "num_dependents",
            "estimated_salary",
            "calls_made",
            "sms_sent",
            "data_used",
            "churn",
        ):
            parsed = _parse_int(values[column])
            if parsed is None:
                errors.add(
                    "invalid_number",
                    f"Value in {column!r} must be an integer.",
                    row_number=row_number,
                    column=column,
                    value=values[column],
                )
                row_has_error = True
            else:
                numbers[column] = parsed

        if "age" in numbers and not 15 <= numbers["age"] <= 100:
            errors.add(
                "age_out_of_range",
                "Age must be between 15 and 100.",
                row_number=row_number,
                column="age",
                value=values["age"],
            )
            row_has_error = True

        if "num_dependents" in numbers and not 0 <= numbers["num_dependents"] <= 20:
            errors.add(
                "dependents_out_of_range",
                "Number of dependents must be between 0 and 20.",
                row_number=row_number,
                column="num_dependents",
                value=values["num_dependents"],
            )
            row_has_error = True

        if "estimated_salary" in numbers and numbers["estimated_salary"] <= 0:
            errors.add(
                "salary_not_positive",
                "Estimated salary must be greater than zero.",
                row_number=row_number,
                column="estimated_salary",
                value=values["estimated_salary"],
            )
            row_has_error = True

        for column in ("calls_made", "sms_sent", "data_used"):
            if column in numbers and numbers[column] < 0:
                errors.add(
                    "negative_value",
                    f"{column} must not be negative.",
                    row_number=row_number,
                    column=column,
                    value=values[column],
                )
                row_has_error = True

        if "churn" in numbers and numbers["churn"] not in {0, 1}:
            errors.add(
                "invalid_churn",
                "Churn must be 0 or 1.",
                row_number=row_number,
                column="churn",
                value=values["churn"],
            )
            row_has_error = True

        if row_has_error:
            continue

        records.append(
            {
                "customer_id": customer_id,
                "telecom_partner": telecom_partner,
                "gender": gender,
                "age": numbers["age"],
                "state": state,
                "city": city,
                "pincode": pincode,
                "date_of_registration": registration_date,
                "num_dependents": numbers["num_dependents"],
                "estimated_salary": numbers["estimated_salary"],
                "calls_made": numbers["calls_made"],
                "sms_sent": numbers["sms_sent"],
                "data_used": numbers["data_used"],
                "churn": bool(numbers["churn"]),
                "source_row_number": row_number,
            }
        )

    if not records:
        if not errors.total:
            errors.add("empty_dataset", "The CSV contains no usable data rows.")
        return _finalise_report(report, errors, warnings, _empty_frame())

    cleaned = pd.DataFrame.from_records(records)
    cleaned = cleaned.loc[:, [*list(REQUIRED_COLUMNS), "source_row_number"]]

    date_max = cleaned["date_of_registration"].max()
    date_min = cleaned["date_of_registration"].min()
    effective_as_of = as_of_date or date_max

    if as_of_date is not None and as_of_date < date_max:
        errors.add(
            "as_of_before_max_date",
            "The requested as-of date precedes the latest registration date.",
            column="date_of_registration",
            value=as_of_date.isoformat(),
        )

    for group_customer_id, group in cleaned.groupby("customer_id", sort=False):
        customer_key = str(group_customer_id)
        genders = sorted(group["gender"].unique().tolist())
        if len(genders) > 1:
            warnings.add(
                "gender_inconsistent",
                f"Customer {customer_key!r} has inconsistent gender values across relationships.",
                row_number=int(group["source_row_number"].iloc[0]),
                column="gender",
                value="/".join(genders),
            )

    duplicate_dates = cleaned.groupby(["customer_id", "date_of_registration"], sort=False)
    for date_key, group in duplicate_dates:
        if len(group) <= 1:
            continue
        date_group_customer, date_group_registration = date_key
        warnings.add(
            "duplicate_registration_date",
            (
                f"Customer {date_group_customer!r} has {len(group)} relationships with the "
                "same registration date; source row order breaks the tie."
            ),
            row_number=int(group["source_row_number"].iloc[0]),
            column="date_of_registration",
            value=str(date_group_registration),
        )

    cleaned = derive_relationships(cleaned, effective_as_of)

    relationship_count = len(cleaned)
    unique_customers = int(cleaned["customer_id"].nunique())
    per_customer = cleaned.groupby("customer_id", sort=False).size()
    multi_customer_count = int((per_customer > 1).sum())
    distribution = {
        str(int(cast(int, count))): int(frequency)
        for count, frequency in per_customer.value_counts().sort_index().items()
    }
    reentry_pairs = int(
        (cleaned.groupby(["customer_id", "telecom_partner"], sort=False).size() > 1).sum()
    )

    relationship_churn_count = int(cleaned["churn"].sum())
    latest = cleaned["is_latest_relationship"]
    current_churn_count = int((latest & cleaned["churn"]).sum())
    historical = ~latest
    historical_churned = int((historical & cleaned["churn"]).sum())

    report.unique_customers = unique_customers
    report.multi_relationship_customers = multi_customer_count
    report.relationship_count_distribution = distribution
    report.reentry_pairs = reentry_pairs
    report.as_of_date = effective_as_of
    report.date_min = date_min
    report.date_max = date_max
    report.relationship_churn_count = relationship_churn_count
    report.relationship_churn_rate = _percentage(relationship_churn_count, relationship_count)
    report.historical_relationships = int(historical.sum())
    report.historical_churned = historical_churned
    report.current_relationships = int(latest.sum())
    report.current_churn_count = current_churn_count
    report.current_churn_rate = _percentage(current_churn_count, int(latest.sum()))

    return _finalise_report(report, errors, warnings, cleaned)


def enforce_upload_limits(
    *,
    size_bytes: int,
    row_count: int,
    max_upload_mb: int,
    max_upload_rows: int,
) -> None:
    """Raise :class:`UploadLimitExceeded` when an upload exceeds config limits."""

    byte_limit = max_upload_mb * 1024 * 1024
    if size_bytes > byte_limit:
        size_mb = size_bytes / (1024 * 1024)
        raise UploadLimitExceeded(f"File is {size_mb:.1f} MB; the limit is {max_upload_mb} MB.")
    if row_count > max_upload_rows:
        raise UploadLimitExceeded(
            f"File has {row_count:,} data rows; the limit is {max_upload_rows:,}."
        )


def estimate_csv_data_rows(data: bytes) -> int:
    """Estimate data rows from line breaks for the pre-parse upload guard.

    In this project's CSV fields never contain embedded line breaks, so the
    estimate is exact.  The post-validation check uses the true row count.
    """

    if not data.strip():
        return 0
    return max(len(data.splitlines()) - 1, 0)
