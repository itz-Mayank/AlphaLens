import json

import numpy as np
import pandas as pd
import pytest
from ml.models.baseline.naive import (
    MajorityClassBaseline,
    NaiveZeroReturnModel,
    PreviousReturnBaseline,
)


def test_naive_zero_return_model_always_predicts_zero():
    model = NaiveZeroReturnModel()
    X = pd.DataFrame({"a": [1, 2, 3]})
    predictions = model.predict(X)
    assert np.all(predictions == 0.0)
    assert len(predictions) == 3


def test_naive_zero_return_model_save_and_load_round_trip(tmp_path):
    model = NaiveZeroReturnModel()
    path = tmp_path / "model.json"
    model.save(path)
    loaded = NaiveZeroReturnModel.load(path)
    assert loaded.model_type == "baseline_zero_return"


def test_previous_return_baseline_echoes_the_feature_column():
    model = PreviousReturnBaseline(feature_column="return_1d")
    X = pd.DataFrame({"return_1d": [0.01, -0.02, 0.0]})
    predictions = model.predict(X)
    np.testing.assert_allclose(predictions, [0.01, -0.02, 0.0], atol=1e-6)


def test_previous_return_baseline_save_and_load_round_trip(tmp_path):
    model = PreviousReturnBaseline(feature_column="return_5d")
    path = tmp_path / "model.json"
    model.save(path)
    loaded = PreviousReturnBaseline.load(path)
    assert loaded.feature_column == "return_5d"


def test_majority_class_baseline_learns_the_most_frequent_class():
    model = MajorityClassBaseline()
    y = pd.Series(["Bullish", "Bullish", "Neutral", "Bearish", "Bullish"])
    model.fit(pd.DataFrame(index=y.index), y)
    predictions = model.predict(pd.DataFrame({"x": [1, 2, 3]}))
    assert set(predictions) == {"Bullish"}
    assert len(predictions) == 3


def test_majority_class_baseline_predict_before_fit_raises():
    model = MajorityClassBaseline()
    with pytest.raises(RuntimeError, match="fit"):
        model.predict(pd.DataFrame({"x": [1]}))


def test_majority_class_baseline_save_and_load_round_trip(tmp_path):
    model = MajorityClassBaseline()
    model.fit(pd.DataFrame(index=range(3)), pd.Series(["Bullish", "Bullish", "Bearish"]))
    path = tmp_path / "model.json"
    model.save(path)
    loaded = MajorityClassBaseline.load(path)
    assert loaded.majority_class == "Bullish"
    assert json.loads(path.read_text())["majority_class"] == "Bullish"
