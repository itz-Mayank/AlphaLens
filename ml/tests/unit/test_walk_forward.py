from __future__ import annotations

from datetime import date

import pytest
from ml.backtest.walk_forward import generate_rolling_windows


class TestGenerateRollingWindows:
    def test_produces_non_overlapping_advancing_windows(self):
        windows = generate_rolling_windows(
            start_date=date(2020, 1, 1),
            end_date=date(2021, 1, 1),
            train_days=180,
            validation_days=30,
            test_days=30,
            step_days=30,
        )
        assert len(windows) > 1
        for earlier, later in zip(windows, windows[1:], strict=False):
            assert later.train_end > earlier.train_end
            assert later.window_index == earlier.window_index + 1

    def test_each_windows_boundaries_are_chronological(self):
        windows = generate_rolling_windows(
            start_date=date(2020, 1, 1),
            end_date=date(2021, 1, 1),
            train_days=180,
            validation_days=30,
            test_days=30,
            step_days=30,
        )
        for window in windows:
            assert window.train_end < window.validation_end < window.test_end

    def test_stops_before_exceeding_end_date(self):
        windows = generate_rolling_windows(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 6, 1),
            train_days=120,
            validation_days=15,
            test_days=15,
            step_days=15,
        )
        for window in windows:
            assert window.test_end <= date(2020, 6, 1)

    def test_no_windows_when_the_range_is_too_short(self):
        windows = generate_rolling_windows(
            start_date=date(2020, 1, 1),
            end_date=date(2020, 2, 1),
            train_days=180,
            validation_days=30,
            test_days=30,
            step_days=30,
        )
        assert windows == []

    def test_is_deterministic(self):
        kwargs = dict(
            start_date=date(2020, 1, 1),
            end_date=date(2021, 1, 1),
            train_days=180,
            validation_days=30,
            test_days=30,
            step_days=45,
        )
        assert generate_rolling_windows(**kwargs) == generate_rolling_windows(**kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            dict(train_days=0, validation_days=30, test_days=30, step_days=30),
            dict(train_days=180, validation_days=0, test_days=30, step_days=30),
            dict(train_days=180, validation_days=30, test_days=0, step_days=30),
            dict(train_days=180, validation_days=30, test_days=30, step_days=0),
        ],
    )
    def test_non_positive_durations_raise(self, kwargs):
        with pytest.raises(ValueError):
            generate_rolling_windows(
                start_date=date(2020, 1, 1), end_date=date(2021, 1, 1), **kwargs
            )
