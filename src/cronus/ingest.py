"""Transactional ingestion service for churn snapshots."""

from __future__ import annotations

import hashlib
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from cronus.db import get_session_factory
from cronus.models import CustomerRelationship, Dataset
from cronus.schemas import (
    DatasetAlreadyExists,
    IngestResult,
    ValidationFailed,
    ValidationReport,
)
from cronus.validation import REQUIRED_COLUMNS, derive_relationships, validate_csv

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true"}:
        return True
    if text in {"0", "false"}:
        return False
    raise ValueError(f"Invalid churn value: {value!r}")


def _prepare_frame(df: pd.DataFrame, as_of_date: date | None) -> tuple[pd.DataFrame, date]:
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing required columns: {missing}")

    working = df.loc[:, list(REQUIRED_COLUMNS)].copy(deep=True)
    if "source_row_number" in df.columns:
        working["source_row_number"] = df["source_row_number"].astype(int).to_numpy()
    else:
        working["source_row_number"] = np.arange(1, len(working) + 1)

    if working.empty:
        raise ValueError("Cannot ingest an empty DataFrame.")
    if working["source_row_number"].duplicated().any():
        raise ValueError("source_row_number values must be unique.")
    if int(working["source_row_number"].min()) < 1:
        raise ValueError("source_row_number values must be >= 1.")

    for column in ("customer_id", "telecom_partner", "state", "city"):
        working[column] = working[column].astype(str).str.strip()
    working["gender"] = working["gender"].astype(str).str.strip().str.upper()
    if not working["gender"].isin(["M", "F"]).all():
        raise ValueError("gender must already be normalised to M/F.")
    working["pincode"] = working["pincode"].astype(str).str.strip().str.zfill(6)
    working["churn"] = working["churn"].map(_coerce_bool)

    integer_columns = (
        "age",
        "num_dependents",
        "estimated_salary",
        "calls_made",
        "sms_sent",
        "data_used",
    )
    for column in integer_columns:
        working[column] = working[column].astype(int)

    try:
        working["registration_date"] = pd.to_datetime(working["date_of_registration"]).dt.date
    except (TypeError, ValueError) as exc:
        raise ValueError("date_of_registration values must be valid dates.") from exc

    maximum_registration = working["registration_date"].max()
    effective_as_of = as_of_date or maximum_registration
    if effective_as_of < maximum_registration:
        raise ValueError("as_of_date cannot precede the latest registration date.")

    derived = derive_relationships(working, effective_as_of)
    return derived, effective_as_of


def ingest_dataframe(
    df: pd.DataFrame,
    *,
    dataset_name: str,
    original_filename: str,
    file_sha256: str,
    as_of_date: date | None = None,
    activate: bool = True,
    replace: bool = False,
    validation_report: ValidationReport | dict[str, Any] | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> IngestResult:
    """Load a validated relationship DataFrame in a single transaction."""

    started = time.perf_counter()

    name = dataset_name.strip()
    if not name:
        raise ValueError("dataset_name must not be empty.")
    filename = original_filename.strip()
    if not filename:
        raise ValueError("original_filename must not be empty.")

    digest = file_sha256.strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("file_sha256 must be a 64-character hexadecimal SHA-256 digest.")

    prepared, effective_as_of = _prepare_frame(df, as_of_date)

    if isinstance(validation_report, ValidationReport):
        report_payload = validation_report.model_dump(mode="json")
        warning_count = validation_report.warning_count
    else:
        report_payload = validation_report or {}
        warning_count = int(report_payload.get("warning_count", 0))

    factory = session_factory or get_session_factory()
    dataset_id: Any = None

    with factory() as session, session.begin():
        existing = session.scalar(select(Dataset).where(Dataset.file_sha256 == digest))
        if existing is not None:
            if not replace:
                raise DatasetAlreadyExists(existing.id, existing.name)
            session.delete(existing)
            session.flush()

        if activate:
            session.execute(
                update(Dataset).where(Dataset.is_active.is_(True)).values(is_active=False)
            )

        dataset = Dataset(
            name=name,
            original_filename=filename,
            file_sha256=digest,
            row_count=len(prepared),
            as_of_date=effective_as_of,
            validation_report=report_payload,
            is_active=activate,
        )
        session.add(dataset)
        session.flush()
        dataset_id = dataset.id

        rows = [
            {
                "dataset_id": dataset_id,
                "source_row_number": int(record["source_row_number"]),
                "customer_id": record["customer_id"],
                "telecom_partner": record["telecom_partner"],
                "gender": record["gender"],
                "age": int(record["age"]),
                "state": record["state"],
                "city": record["city"],
                "pincode": record["pincode"],
                "registration_date": record["registration_date"],
                "num_dependents": int(record["num_dependents"]),
                "estimated_salary": int(record["estimated_salary"]),
                "calls_made": int(record["calls_made"]),
                "sms_sent": int(record["sms_sent"]),
                "data_used": int(record["data_used"]),
                "churn": bool(record["churn"]),
                "relationship_seq": int(record["relationship_seq"]),
                "relationship_count": int(record["relationship_count"]),
                "is_latest_relationship": bool(record["is_latest_relationship"]),
                "tenure_days": int(record["tenure_days"]),
            }
            for record in prepared.to_dict(orient="records")
        ]
        session.execute(insert(CustomerRelationship), rows)

    elapsed = round(time.perf_counter() - started, 3)
    return IngestResult(
        dataset_id=dataset_id,
        dataset_name=name,
        row_count=len(prepared),
        warning_count=warning_count,
        elapsed_seconds=elapsed,
    )


def ingest_csv(
    source: Path | bytes,
    *,
    dataset_name: str | None = None,
    original_filename: str | None = None,
    file_sha256: str | None = None,
    as_of_date: date | None = None,
    activate: bool = True,
    replace: bool = False,
    session_factory: sessionmaker[Session] | None = None,
) -> IngestResult:
    """Validate and ingest a CSV path or raw bytes via the single ingestion path."""

    data = source.read_bytes() if isinstance(source, Path) else bytes(source)
    report, cleaned = validate_csv(data, as_of_date=as_of_date)
    if report.has_errors:
        raise ValidationFailed(report)

    digest = file_sha256 or hashlib.sha256(data).hexdigest()
    resolved_filename = original_filename
    if resolved_filename is None:
        resolved_filename = source.name if isinstance(source, Path) else "upload.csv"
    resolved_name = dataset_name or Path(resolved_filename).stem or "churn-dataset"

    return ingest_dataframe(
        cleaned,
        dataset_name=resolved_name,
        original_filename=resolved_filename,
        file_sha256=digest,
        as_of_date=report.as_of_date,
        activate=activate,
        replace=replace,
        validation_report=report,
        session_factory=session_factory,
    )
