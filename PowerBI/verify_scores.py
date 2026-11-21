#!/usr/bin/env python3
"""Compare Power BI scores with the Streamlit scoring path.

Build-time check, not part of the application. After the PBIX loads, export the
``ScoredRelationships`` table to CSV and run:

    uv run python PowerBI/verify_scores.py path/to/exported_scores.csv

The script refits the fixed baseline pipeline on the active current-relationship
frame, scores every row, and compares the result with the Power BI export. It
exits with code 1 when the probabilities differ by more than 1e-6 or when
either flag column disagrees.
"""

# ruff: noqa: E402 - the script bootstraps src/ before the cronus imports.

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from cronus.db import session_scope
from cronus.modeling import predict_churn
from cronus.modeling.serving import (
    FINAL_THRESHOLD,
    HIGH_RECALL_THRESHOLD,
    fit_scoring_model,
)
from cronus.repository import get_active_dataset_summary, get_current_relationships

TOLERANCE = 1e-6
PROBABILITY_COLUMN = "churn_probability"
DEFAULT_FLAG = "predicted_churn_default"
RECALL70_FLAG = "predicted_churn_recall70"


def load_powerbi_export(csv_path: Path) -> pd.DataFrame:
    """Load a Power BI table export and normalise its column names and flags."""

    frame = pd.read_csv(csv_path, dtype={"customer_id": str})
    frame = frame.rename(columns=lambda name: str(name).removeprefix("Sum of ").strip())

    required = {PROBABILITY_COLUMN, DEFAULT_FLAG, RECALL70_FLAG}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Missing Power BI columns: {', '.join(missing)}")
    if "customer_id" not in frame.columns:
        raise ValueError("Missing Power BI column: customer_id")

    frame["customer_id"] = frame["customer_id"].astype(str).str.strip()
    frame[PROBABILITY_COLUMN] = pd.to_numeric(frame[PROBABILITY_COLUMN], errors="raise")
    for column in (DEFAULT_FLAG, RECALL70_FLAG):
        frame[column] = _as_boolean(frame[column])
    return frame


def compute_python_scores() -> pd.DataFrame:
    """Score the active current-relationship frame with the Streamlit path."""

    with session_scope() as session:
        summary = get_active_dataset_summary(session)
        if summary is None:
            raise ValueError("No active dataset")
        frame = get_current_relationships(session, summary.dataset_id)

    scoring_model = fit_scoring_model(frame, dataset_id=str(summary.dataset_id))
    probabilities = predict_churn(scoring_model.model, frame)
    return pd.DataFrame(
        {
            "customer_id": frame["customer_id"].astype(str).str.strip().to_numpy(),
            f"{PROBABILITY_COLUMN}_python": probabilities,
            f"{DEFAULT_FLAG}_python": probabilities >= FINAL_THRESHOLD,
            f"{RECALL70_FLAG}_python": probabilities >= HIGH_RECALL_THRESHOLD,
        }
    )


def compare_scores(
    powerbi: pd.DataFrame,
    python: pd.DataFrame,
    *,
    tolerance: float = TOLERANCE,
) -> dict[str, Any]:
    """Return the parity result for one Power BI export and the Python scores."""

    if len(powerbi) != len(python):
        raise ValueError(f"Row count differs: Power BI {len(powerbi):,}, Python {len(python):,}")

    merged = powerbi.merge(python, on="customer_id", how="outer", indicator=True)
    unmatched = int((merged["_merge"] != "both").sum())
    if unmatched:
        raise ValueError(f"{unmatched} customer IDs do not appear in both frames")
    merged = merged.drop(columns="_merge")

    probability = pd.to_numeric(merged[PROBABILITY_COLUMN], errors="raise")
    python_probability = pd.to_numeric(merged[f"{PROBABILITY_COLUMN}_python"], errors="raise")
    difference = (probability - python_probability).abs()

    default_match = (merged[DEFAULT_FLAG] == merged[f"{DEFAULT_FLAG}_python"]).all()
    recall70_match = (merged[RECALL70_FLAG] == merged[f"{RECALL70_FLAG}_python"]).all()
    max_difference = float(difference.max())

    return {
        "rows_compared": len(merged),
        "max_probability_diff": max_difference,
        "mean_probability_diff": float(difference.mean()),
        "probability_match": max_difference <= tolerance,
        "default_flag_match": bool(default_match),
        "recall70_flag_match": bool(recall70_match),
        "default_threshold": FINAL_THRESHOLD,
        "recall70_threshold": HIGH_RECALL_THRESHOLD,
        "tolerance": tolerance,
    }


def _as_boolean(values: pd.Series) -> pd.Series:
    if values.dtype == bool:
        return values
    normalized = values.astype(str).str.strip().str.lower()
    mapping = {"true": True, "false": False, "1": True, "0": False}
    unknown = sorted(set(normalized) - set(mapping))
    if unknown:
        raise ValueError(f"Unexpected flag values: {', '.join(unknown)}")
    return normalized.map(mapping).astype(bool)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Usage: uv run python PowerBI/verify_scores.py <exported_scores.csv>")
        return 2

    export_path = Path(argv[1])
    if not export_path.exists():
        print(f"File not found: {export_path}")
        return 2

    print("Loading the Power BI export...")
    powerbi = load_powerbi_export(export_path)
    print(f"  Rows: {len(powerbi):,}")

    print("Scoring the active current frame with the Streamlit path...")
    python = compute_python_scores()
    print(f"  Rows: {len(python):,}")

    result = compare_scores(powerbi, python)
    print("\nParity result")
    for key, value in result.items():
        print(f"  {key}: {value}")

    passed = (
        result["probability_match"]
        and result["default_flag_match"]
        and result["recall70_flag_match"]
    )
    if passed:
        print("\nPASS: Power BI matches the Streamlit scores.")
        return 0

    print("\nFAIL: Power BI does not match the Streamlit scores.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
