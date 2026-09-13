from __future__ import annotations

import math

from ml.backtest.signals import SignalRule, classification_signal, return_sign_signal


class TestClassificationSignal:
    def test_bullish_is_long(self):
        assert classification_signal("Bullish") == 1.0

    def test_neutral_is_flat(self):
        assert classification_signal("Neutral") == 0.0

    def test_bearish_is_flat_by_default(self):
        assert classification_signal("Bearish") == 0.0

    def test_bearish_is_short_only_when_explicitly_allowed(self):
        rule = SignalRule(allow_short=True)
        assert classification_signal("Bearish", rule) == -1.0

    def test_missing_prediction_is_flat(self):
        assert classification_signal(None) == 0.0


class TestReturnSignSignal:
    def test_positive_return_is_long(self):
        assert return_sign_signal(0.02) == 1.0

    def test_negative_return_is_flat_by_default(self):
        assert return_sign_signal(-0.02) == 0.0

    def test_negative_return_is_short_only_when_explicitly_allowed(self):
        assert return_sign_signal(-0.02, allow_short=True) == -1.0

    def test_zero_return_is_flat(self):
        assert return_sign_signal(0.0) == 0.0

    def test_missing_return_is_flat(self):
        assert return_sign_signal(None) == 0.0

    def test_nan_return_is_flat(self):
        assert return_sign_signal(math.nan) == 0.0
