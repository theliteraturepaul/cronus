"""Pydantic contracts shared by validation, ingestion, repositories and the app."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class ValidationIssue(BaseModel):
    """A single validation error or warning."""

    code: str
    message: str
    row_number: int | None = None
    column: str | None = None
    value: str | None = None


class ValidationReport(BaseModel):
    """Outcome of validating one churn CSV.

    Rates are percentages rounded to two decimal places.  Relationship churn
    and current-base churn are deliberately reported separately.
    """

    row_count: int = 0
    column_count: int = 0
    unique_customers: int = 0
    multi_relationship_customers: int = 0
    relationship_count_distribution: dict[str, int] = Field(default_factory=dict)
    reentry_pairs: int = 0
    as_of_date: date | None = None
    date_min: date | None = None
    date_max: date | None = None
    relationship_churn_count: int = 0
    relationship_churn_rate: float = 0.0
    historical_relationships: int = 0
    historical_churned: int = 0
    current_relationships: int = 0
    current_churn_count: int = 0
    current_churn_rate: float = 0.0
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    errors_truncated: bool = False
    warnings_truncated: bool = False

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0


class DatasetInfo(BaseModel):
    """Row shown in the datasets table."""

    id: uuid.UUID
    name: str
    relationship_count: int
    unique_customers: int
    relationship_churn_rate: float
    current_churn_rate: float
    is_active: bool
    uploaded_at: datetime
    file_sha256_prefix: str


class DatasetLookup(BaseModel):
    """Minimal existing-dataset information for duplicate uploads."""

    id: uuid.UUID
    name: str
    relationship_count: int
    is_active: bool


class ActiveDatasetSummary(BaseModel):
    """Dual-grain summary of the currently active dataset."""

    dataset_id: uuid.UUID
    dataset_name: str
    relationship_count: int
    unique_customers: int
    relationship_churn_count: int
    relationship_churn_rate: float
    current_relationship_count: int
    current_churn_count: int
    current_churn_rate: float
    multi_relationship_customers: int
    relationship_count_distribution: dict[str, int]
    reentry_pairs: int
    historical_relationships: int
    historical_churned: int
    min_registration_date: date | None
    max_registration_date: date | None
    as_of_date: date
    partner_count: int


class ConnectionInfo(BaseModel):
    """Live Neon/PostgreSQL connection details."""

    server_version: str
    database: str
    user: str
    latency_ms: float


class IngestResult(BaseModel):
    """Summary returned by a successful ingestion."""

    dataset_id: uuid.UUID
    dataset_name: str
    row_count: int
    warning_count: int
    elapsed_seconds: float


class AccountInfo(BaseModel):
    """One application account, without the password hash."""

    id: uuid.UUID
    email: str
    username: str | None = None
    display_name: str
    created_at: datetime
    last_login_at: datetime | None = None
    is_admin: bool = False


class VisitorSnapshot(BaseModel):
    """Aggregate visitor counts shown in the site banner."""

    total_visits: int
    registered_users: int
    active_sessions: int


class CronusError(Exception):
    """Base class for expected, user-facing Cronus errors."""


class ValidationFailed(CronusError):
    """Raised when a CSV fails hard validation and nothing was written."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(f"CSV validation failed with {report.error_count} error(s)")


class DatasetAlreadyExists(CronusError):
    """Raised when the same file hash is already loaded."""

    def __init__(self, dataset_id: uuid.UUID, dataset_name: str) -> None:
        self.dataset_id = dataset_id
        self.dataset_name = dataset_name
        super().__init__(
            f"Dataset {dataset_name!r} ({dataset_id}) was already uploaded. "
            "Activate it or replace it explicitly."
        )


class DatasetNotFound(CronusError):
    """Raised when a requested dataset id does not exist."""


class UploadLimitExceeded(CronusError):
    """Raised when a file exceeds the configured size or row limit."""


class DuplicateAccount(CronusError):
    """Raised when an email address or username already has an account."""

    def __init__(self, email: str) -> None:
        self.email = email
        super().__init__(f"An account for {email!r} already exists.")
