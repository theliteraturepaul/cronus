"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from cronus.schemas import ValidationReport
from cronus.validation import validate_csv

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = REPO_ROOT / "Dataset" / "project_dataset.csv"


@pytest.fixture(scope="session")
def dataset_bytes() -> bytes:
    return DATASET_PATH.read_bytes()


@pytest.fixture(scope="session")
def baseline(dataset_bytes: bytes) -> tuple[ValidationReport, pd.DataFrame]:
    return validate_csv(dataset_bytes)
