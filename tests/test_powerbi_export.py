"""Power BI export and Power Query parity tests (no database)."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from cronus.modeling import (
    fit_final_model,
    make_xy,
    predict_churn,
    prepare_current_frame,
)
from cronus.modeling.training import FittedModel
from cronus.schemas import ValidationReport

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPORT_PATH = REPO_ROOT / "PowerBI" / "powerbi_model_export.json"
M_SCRIPT_PATH = REPO_ROOT / "PowerBI" / "PowerQuery_M_Scoring.txt"
FINAL_PARAMS = {"classifier__C": 0.1}
FINAL_THRESHOLD = 0.184
HIGH_RECALL_THRESHOLD = 0.0981
INFREQUENT_STATES = ["Nagaland", "Puducherry", "Sikkim"]


def _load_export() -> dict[str, Any]:
    return json.loads(EXPORT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fitted(baseline: tuple[ValidationReport, pd.DataFrame]) -> tuple[pd.DataFrame, FittedModel]:
    current = prepare_current_frame(baseline[1])
    model = fit_final_model(
        current,
        model_name="logistic",
        include_relationship_count=False,
        params=FINAL_PARAMS,
        threshold=FINAL_THRESHOLD,
    )
    return current, model


def test_export_matches_fitted_pipeline(fitted: tuple[pd.DataFrame, FittedModel]) -> None:
    _, model = fitted
    export = _load_export()
    preprocessor = model.pipeline.named_steps["preprocessor"]
    classifier = model.pipeline.named_steps["classifier"]
    scaler = preprocessor.named_transformers_["numeric"]
    encoder = preprocessor.named_transformers_["categorical"]

    feature_names = [str(name) for name in preprocessor.get_feature_names_out()]
    assert feature_names == export["output_feature_names"]
    assert len(feature_names) == 43

    np.testing.assert_allclose(classifier.coef_[0], export["coefficients"], rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(
        classifier.intercept_[0], export["intercept"], rtol=1e-10, atol=1e-10
    )

    np.testing.assert_allclose(scaler.mean_, export["numeric_mean"], rtol=1e-10, atol=1e-10)
    np.testing.assert_allclose(scaler.scale_, export["numeric_scale"], rtol=1e-10, atol=1e-10)

    categories = [[str(value) for value in values] for values in encoder.categories_]
    assert categories == export["categorical_categories"]
    infrequent = [
        [] if values is None else [str(value) for value in values]
        for values in encoder.infrequent_categories_
    ]
    assert infrequent[2] == INFREQUENT_STATES
    assert export["threshold_default"] == FINAL_THRESHOLD
    assert export["threshold_recall70"] == HIGH_RECALL_THRESHOLD


def test_export_reproduces_python_scores(fitted: tuple[pd.DataFrame, FittedModel]) -> None:
    current, model = fitted
    export = _load_export()
    probabilities = _score_from_export(current, export)
    python_probabilities = predict_churn(model, current)

    difference = np.abs(probabilities - python_probabilities)
    assert difference.max() <= 1e-12
    assert int((probabilities >= FINAL_THRESHOLD).sum()) == 1_180
    assert int((probabilities >= HIGH_RECALL_THRESHOLD).sum()) == 3_286


def test_m_query_matches_export() -> None:
    export = _load_export()
    text = M_SCRIPT_PATH.read_text(encoding="utf-8")

    for query_number in range(1, 6):
        assert f"QUERY {query_number} of 5" in text

    coefficients = _record(_block(text, "Coefficients = [", "]"))
    assert coefficients == export["coefficient_map"]
    assert _number_field(text, "Model_Intercept") == export["intercept"]
    assert _number_field(text, "Threshold_Default") == export["threshold_default"]
    assert _number_field(text, "Threshold_Recall70") == export["threshold_recall70"]

    assert _bare_record(_block(text, "Num_Mean = [", "]")) == dict(
        zip(export["numeric_features"], export["numeric_mean"], strict=True)
    )
    assert _bare_record(_block(text, "Num_Scale = [", "]")) == dict(
        zip(export["numeric_features"], export["numeric_scale"], strict=True)
    )

    partner_categories = _list(_block(text, "Cat_TelecomPartner = {", "}"))
    gender_categories = _list(_block(text, "Cat_Gender = {", "}"))
    frequent_states = _list(_block(text, "Cat_StateFrequent = {", "}"))
    infrequent_states = _list(_block(text, "Cat_StateInfrequent = {", "}"))

    export_partner, export_gender, export_states = export["categorical_categories"]
    assert partner_categories == export_partner
    assert gender_categories == export_gender
    assert infrequent_states == INFREQUENT_STATES
    assert set(frequent_states) | set(infrequent_states) == set(export_states)
    assert frequent_states == [state for state in export_states if state not in INFREQUENT_STATES]


def _score_from_export(frame: pd.DataFrame, export: dict[str, Any]) -> np.ndarray:
    """Reproduce the Power Query formula in Python."""

    features, _ = make_xy(frame, include_relationship_count=False)
    coefficients = dict(zip(export["output_feature_names"], export["coefficients"], strict=True))
    means = dict(zip(export["numeric_features"], export["numeric_mean"], strict=True))
    scales = dict(zip(export["numeric_features"], export["numeric_scale"], strict=True))
    partner_categories, gender_categories, state_categories = export["categorical_categories"]
    frequent_states = set(state_categories) - set(INFREQUENT_STATES)

    scores = np.empty(len(features), dtype=float)
    for position, row in enumerate(features.to_dict("records")):
        score = float(export["intercept"])
        if row["telecom_partner"] in partner_categories:
            score += coefficients[f"telecom_partner_{row['telecom_partner']}"]
        if row["gender"] in gender_categories:
            score += coefficients[f"gender_{row['gender']}"]
        if row["state"] in frequent_states:
            score += coefficients[f"state_{row['state']}"]
        elif row["state"] in INFREQUENT_STATES:
            score += coefficients["state_infrequent_sklearn"]
        for feature in export["numeric_features"]:
            standardized = (float(row[feature]) - means[feature]) / scales[feature]
            score += standardized * coefficients[feature]
        scores[position] = 1.0 / (1.0 + math.exp(-score))
    return scores


def _block(text: str, marker: str, closing: str) -> str:
    start = text.index(marker) + len(marker)
    return text[start : text.index(closing, start)]


def _record(block: str) -> dict[str, float]:
    pattern = re.compile(r'#"([^"]+)"\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)')
    return {name: float(value) for name, value in pattern.findall(block)}


def _bare_record(block: str) -> dict[str, float]:
    pattern = re.compile(r"(\w+)\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)")
    return {name: float(value) for name, value in pattern.findall(block)}


def _number_field(text: str, name: str) -> float:
    match = re.search(rf"\b{name}\s*=\s*(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", text)
    assert match is not None
    return float(match.group(1))


def _list(block: str) -> list[str]:
    return re.findall(r'"([^"]+)"', block)
