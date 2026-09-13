"""Tests for `ml.explainability.shap_explainer`. Not just "SHAP executes
without error" — these check the output CONTRACT is meaningful: correct
feature names, correct feature values (matching the input row, not
fabricated), a real positive/negative split, and top-N behavior."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from ml.datasets.tabular import add_next_day_return, build_tabular_dataset
from ml.explainability.shap_explainer import (
    explain_direction_prediction,
    explain_return_prediction,
)
from ml.features.pipeline import FEATURE_COLUMNS, build_features
from ml.models.xgboost.model import (
    XGBoostDirectionModel,
    XGBoostHyperparameters,
    XGBoostReturnModel,
)
from ml.targets.targets import (
    CLASS_NAMES,
    classify_return,
    derive_classification_thresholds,
    future_return,
)

from tests.helpers import make_synthetic_ohlcv


@pytest.fixture(scope="module")
def fitted_models():
    df = make_synthetic_ohlcv(tickers=("AAA", "BBB"), num_days=150, seed=11)
    featured = build_features(df)
    featured["future_return"] = future_return(featured, horizon_days=5)
    bearish, bullish = derive_classification_thresholds(featured["future_return"])
    featured["future_class"] = classify_return(
        featured["future_return"], bearish_threshold=bearish, bullish_threshold=bullish
    )
    featured = add_next_day_return(featured)
    tab = build_tabular_dataset(featured, feature_columns=FEATURE_COLUMNS)

    return_model = XGBoostReturnModel(XGBoostHyperparameters(n_estimators=10))
    return_model.fit(tab.X, tab.y_return)
    direction_model = XGBoostDirectionModel(XGBoostHyperparameters(n_estimators=10))
    direction_model.fit(tab.X, tab.y_class)

    feature_row = featured.dropna(subset=FEATURE_COLUMNS).iloc[-1]
    return return_model, direction_model, feature_row


class TestExplainReturnPrediction:
    def test_returns_exactly_top_n_contributions(self, fitted_models):
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=5
        )
        assert len(contributions) == 5

    def test_top_n_is_configurable(self, fitted_models):
        return_model, _, feature_row = fitted_models
        assert (
            len(explain_return_prediction(return_model, feature_row, FEATURE_COLUMNS, top_n=3)) == 3
        )
        assert (
            len(explain_return_prediction(return_model, feature_row, FEATURE_COLUMNS, top_n=10))
            == 10
        )

    def test_feature_names_come_from_the_real_feature_set(self, fitted_models):
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=len(FEATURE_COLUMNS)
        )
        assert {c.feature for c in contributions} == set(FEATURE_COLUMNS)

    def test_feature_values_match_the_input_row_not_fabricated(self, fitted_models):
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=len(FEATURE_COLUMNS)
        )
        for c in contributions:
            assert c.value == pytest.approx(float(feature_row[c.feature]))

    def test_direction_matches_the_sign_of_the_contribution(self, fitted_models):
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=len(FEATURE_COLUMNS)
        )
        for c in contributions:
            expected = "positive" if c.contribution >= 0 else "negative"
            assert c.direction == expected

    def test_results_are_ranked_by_absolute_contribution_descending(self, fitted_models):
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=len(FEATURE_COLUMNS)
        )
        magnitudes = [abs(c.contribution) for c in contributions]
        assert magnitudes == sorted(magnitudes, reverse=True)

    def test_deterministic_across_repeated_calls(self, fitted_models):
        return_model, _, feature_row = fitted_models
        first = explain_return_prediction(return_model, feature_row, FEATURE_COLUMNS, top_n=5)
        second = explain_return_prediction(return_model, feature_row, FEATURE_COLUMNS, top_n=5)
        assert [c.as_dict() for c in first] == [c.as_dict() for c in second]

    def test_contributions_sum_reasonably_close_to_prediction_minus_base(self, fitted_models):
        """A real sanity check on SHAP's additive property (base value +
        sum(all contributions) ~= model output) — not required for the
        top-N result exactly (since only top-N are returned), but checked
        here against the *full* feature set to prove the values genuinely
        come from a real SHAP decomposition."""
        return_model, _, feature_row = fitted_models
        contributions = explain_return_prediction(
            return_model, feature_row, FEATURE_COLUMNS, top_n=len(FEATURE_COLUMNS)
        )
        total_contribution = sum(c.contribution for c in contributions)
        X = pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])
        prediction = float(return_model.predict(X)[0])
        # Base value + total SHAP contribution should reconstruct the
        # model's own prediction (within float tolerance).
        import shap

        explainer = shap.TreeExplainer(return_model.native_estimator)
        base_value = float(np.asarray(explainer.expected_value).reshape(-1)[0])
        assert base_value + total_contribution == pytest.approx(prediction, abs=1e-3)


class TestExplainDirectionPrediction:
    def test_returns_top_n_for_the_predicted_class(self, fitted_models):
        _, direction_model, feature_row = fitted_models
        X = pd.DataFrame([feature_row[list(FEATURE_COLUMNS)].to_dict()])
        predicted_class = direction_model.predict(X)[0]
        predicted_class_index = list(CLASS_NAMES).index(predicted_class)

        contributions = explain_direction_prediction(
            direction_model,
            feature_row,
            FEATURE_COLUMNS,
            predicted_class_index=predicted_class_index,
            top_n=5,
        )
        assert len(contributions) == 5
        assert {c.feature for c in contributions}.issubset(set(FEATURE_COLUMNS))

    def test_different_classes_give_different_contributions(self, fitted_models):
        """Explaining "why Bullish" and "why Bearish" for the same row must
        not produce identical numbers — they're different SHAP slices."""
        _, direction_model, feature_row = fitted_models
        bullish_index = list(CLASS_NAMES).index("Bullish")
        bearish_index = list(CLASS_NAMES).index("Bearish")

        bullish_contributions = explain_direction_prediction(
            direction_model,
            feature_row,
            FEATURE_COLUMNS,
            predicted_class_index=bullish_index,
            top_n=len(FEATURE_COLUMNS),
        )
        bearish_contributions = explain_direction_prediction(
            direction_model,
            feature_row,
            FEATURE_COLUMNS,
            predicted_class_index=bearish_index,
            top_n=len(FEATURE_COLUMNS),
        )
        bullish_by_feature = {c.feature: c.contribution for c in bullish_contributions}
        bearish_by_feature = {c.feature: c.contribution for c in bearish_contributions}
        assert bullish_by_feature != bearish_by_feature

    def test_feature_values_match_the_input_row(self, fitted_models):
        _, direction_model, feature_row = fitted_models
        contributions = explain_direction_prediction(
            direction_model,
            feature_row,
            FEATURE_COLUMNS,
            predicted_class_index=1,
            top_n=len(FEATURE_COLUMNS),
        )
        for c in contributions:
            assert c.value == pytest.approx(float(feature_row[c.feature]))
