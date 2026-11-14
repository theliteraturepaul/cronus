"""Validation and relationship-derivation tests (no database)."""

from __future__ import annotations

import csv
import io
from datetime import date

import pandas as pd
import pytest

from cronus.schemas import ValidationReport
from cronus.validation import (
    REQUIRED_COLUMNS,
    derive_relationships,
    estimate_csv_data_rows,
    validate_csv,
)

HEADER = list(REQUIRED_COLUMNS)


def _valid_row(**overrides: str) -> list[str]:
    values = {
        "customer_id": "CUST-1",
        "telecom_partner": "Airtel",
        "gender": "M",
        "age": "30",
        "state": "Delhi",
        "city": "New Delhi",
        "pincode": "110001",
        "date_of_registration": "01-01-2023",
        "num_dependents": "1",
        "estimated_salary": "50000",
        "calls_made": "10",
        "sms_sent": "5",
        "data_used": "100",
        "churn": "0",
    }
    values.update(overrides)
    return [values[column] for column in HEADER]


def _csv_bytes(
    rows: list[list[str]],
    *,
    header: list[str] | None = None,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header or HEADER)
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _codes(report: ValidationReport, issue_type: str = "errors") -> set[str]:
    issues = report.errors if issue_type == "errors" else report.warnings
    return {issue.code for issue in issues}


def test_baseline_validation_metrics(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    report, cleaned = baseline
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.row_count == 10_000
    assert report.column_count == 14
    assert report.unique_customers == 8_860
    assert report.multi_relationship_customers == 1_020
    assert report.relationship_count_distribution == {"1": 7_840, "2": 900, "3": 120}
    assert report.reentry_pairs == 33
    assert report.as_of_date == date(2023, 5, 4)
    assert report.date_min == date(2020, 1, 1)
    assert report.date_max == date(2023, 5, 4)
    assert report.relationship_churn_count == 1_987
    assert report.relationship_churn_rate == 19.87
    assert report.historical_relationships == 1_140
    assert report.historical_churned == 1_140
    assert report.current_relationships == 8_860
    assert report.current_churn_count == 847
    assert report.current_churn_rate == 9.56
    assert cleaned.shape == (10_000, 19)
    assert cleaned["source_row_number"].tolist() == list(range(1, 10_001))
    assert bool((~cleaned["is_latest_relationship"]).sum() == 1_140)
    assert bool(cleaned.loc[~cleaned["is_latest_relationship"], "churn"].all())


def test_relationship_derivation_sequence_and_tenure() -> None:
    frame = pd.DataFrame(
        [
            {"customer_id": "A", "date_of_registration": date(2023, 1, 1)},
            {"customer_id": "A", "date_of_registration": date(2023, 3, 1)},
            {"customer_id": "A", "date_of_registration": date(2023, 5, 1)},
        ]
    )
    result = derive_relationships(frame, date(2023, 6, 1))
    assert result["relationship_seq"].tolist() == [1, 2, 3]
    assert result["relationship_count"].tolist() == [3, 3, 3]
    assert result["is_latest_relationship"].tolist() == [False, False, True]
    assert result["tenure_days"].tolist() == [59, 61, 31]
    assert result["source_row_number"].tolist() == [1, 2, 3]


def test_relationship_derivation_orders_ties_by_source_row() -> None:
    frame = pd.DataFrame(
        [
            {
                "customer_id": "A",
                "date_of_registration": date(2023, 1, 1),
                "source_row_number": 20,
            },
            {
                "customer_id": "A",
                "date_of_registration": date(2023, 1, 1),
                "source_row_number": 10,
            },
        ]
    )
    result = derive_relationships(frame, date(2023, 2, 1))
    ordered = result.sort_values("source_row_number")
    assert ordered["relationship_seq"].tolist() == [1, 2]
    assert ordered["tenure_days"].tolist() == [0, 31]


def test_derive_relationships_does_not_mutate_input() -> None:
    frame = pd.DataFrame([{"customer_id": "A", "date_of_registration": date(2023, 1, 1)}])
    original_columns = list(frame.columns)
    derive_relationships(frame, date(2023, 2, 1))
    assert list(frame.columns) == original_columns


def test_multi_provider_and_reentry_are_accepted_without_warnings(
    baseline: tuple[ValidationReport, pd.DataFrame],
) -> None:
    report, _ = baseline
    assert report.error_count == 0
    assert report.warning_count == 0
    assert not any("duplicate" in issue.message.lower() for issue in report.warnings)


def test_explicit_reentry_pair_is_accepted() -> None:
    rows = [
        _valid_row(
            customer_id="RET-1", telecom_partner="Airtel", date_of_registration="01-01-2021"
        ),
        _valid_row(customer_id="RET-1", telecom_partner="Jio", date_of_registration="01-01-2022"),
        _valid_row(
            customer_id="RET-1", telecom_partner="Airtel", date_of_registration="01-01-2023"
        ),
    ]
    report, cleaned = validate_csv(_csv_bytes(rows))
    assert report.error_count == 0
    assert report.multi_relationship_customers == 1
    assert report.reentry_pairs == 1
    assert len(cleaned) == 3


def test_missing_column_is_a_hard_error() -> None:
    header = [column for column in HEADER if column != "churn"]
    row = _valid_row()
    row.pop(HEADER.index("churn"))
    report, _ = validate_csv(_csv_bytes([row], header=header))
    assert "missing_column" in _codes(report)
    assert report.error_count >= 1


def test_empty_file_is_a_hard_error() -> None:
    report, cleaned = validate_csv(b"")
    assert "empty_file" in _codes(report)
    assert report.row_count == 0
    assert cleaned.empty


def test_header_only_file_is_a_hard_error() -> None:
    report, _ = validate_csv(_csv_bytes([]))
    assert "empty_dataset" in _codes(report)


def test_invalid_date_reports_row_number() -> None:
    report, _ = validate_csv(_csv_bytes([_valid_row(date_of_registration="31-02-2023")]))
    assert "invalid_date" in _codes(report)
    assert report.errors[0].row_number == 1


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("churn", "2", "invalid_churn"),
        ("calls_made", "-1", "negative_value"),
        ("age", "200", "age_out_of_range"),
        ("num_dependents", "21", "dependents_out_of_range"),
        ("estimated_salary", "0", "salary_not_positive"),
        ("pincode", "ABCDEF", "invalid_pincode"),
    ],
)
def test_invalid_values_are_hard_errors(field: str, value: str, code: str) -> None:
    report, _ = validate_csv(_csv_bytes([_valid_row(**{field: value})]))
    assert code in _codes(report)


def test_missing_value_is_a_hard_error() -> None:
    report, _ = validate_csv(_csv_bytes([_valid_row(city="")]))
    assert "missing_value" in _codes(report)
    assert any(issue.column == "city" for issue in report.errors)


def test_gender_normalisation() -> None:
    report, cleaned = validate_csv(
        _csv_bytes(
            [
                _valid_row(customer_id="G-1", gender="male"),
                _valid_row(
                    customer_id="G-2",
                    gender="Female",
                    date_of_registration="02-01-2023",
                ),
            ]
        )
    )
    assert report.error_count == 0
    assert set(cleaned["gender"]) == {"M", "F"}


def test_gender_inconsistency_is_only_a_warning() -> None:
    report, _ = validate_csv(
        _csv_bytes(
            [
                _valid_row(customer_id="G-3", date_of_registration="01-01-2022"),
                _valid_row(
                    customer_id="G-3",
                    gender="F",
                    date_of_registration="01-01-2023",
                ),
            ]
        )
    )
    assert report.error_count == 0
    assert "gender_inconsistent" in _codes(report, "warnings")


def test_extra_column_is_dropped_with_warning() -> None:
    header = [*HEADER, "extra_notes"]
    report, cleaned = validate_csv(_csv_bytes([[*_valid_row(), "ignore me"]], header=header))
    assert "extra_column" in _codes(report, "warnings")
    assert "extra_notes" not in cleaned.columns


def test_pincode_zero_padding_and_excel_artifact() -> None:
    report, cleaned = validate_csv(
        _csv_bytes(
            [
                _valid_row(customer_id="P-1", pincode="12345"),
                _valid_row(
                    customer_id="P-2",
                    pincode="123456.0",
                    date_of_registration="02-01-2023",
                ),
            ]
        )
    )
    assert report.error_count == 0
    assert "pincode_zero_padded" in _codes(report, "warnings")
    assert "pincode_excel_artifact" in _codes(report, "warnings")
    assert set(cleaned["pincode"]) == {"012345", "123456"}


def test_duplicate_registration_date_is_only_a_warning() -> None:
    report, cleaned = validate_csv(
        _csv_bytes(
            [
                _valid_row(customer_id="D-1"),
                _valid_row(customer_id="D-1", telecom_partner="Jio"),
            ]
        )
    )
    assert report.error_count == 0
    assert "duplicate_registration_date" in _codes(report, "warnings")
    assert cleaned["relationship_count"].tolist() == [2, 2]


def test_as_of_date_before_max_registration_is_a_hard_error() -> None:
    report, _ = validate_csv(
        _csv_bytes([_valid_row(date_of_registration="01-01-2023")]),
        as_of_date=date(2022, 12, 31),
    )
    assert "as_of_before_max_date" in _codes(report)


def test_as_of_date_override_sets_latest_tenure() -> None:
    report, cleaned = validate_csv(
        _csv_bytes([_valid_row(date_of_registration="01-01-2023")]),
        as_of_date=date(2023, 2, 1),
    )
    assert report.error_count == 0
    assert report.as_of_date == date(2023, 2, 1)
    assert cleaned["tenure_days"].tolist() == [31]


def test_validation_does_not_mutate_csv_bytes(dataset_bytes: bytes) -> None:
    original = bytes(dataset_bytes)
    validate_csv(dataset_bytes)
    assert dataset_bytes == original


def test_estimate_csv_data_rows() -> None:
    assert estimate_csv_data_rows(b"") == 0
    assert estimate_csv_data_rows(_csv_bytes([])) == 0
    assert estimate_csv_data_rows(_csv_bytes([_valid_row()])) == 1
    assert estimate_csv_data_rows(_csv_bytes([_valid_row(), _valid_row()])) == 2
