from datetime import date, timedelta
from decimal import Decimal

from app.providers.base import OHLCVBar
from app.services.market_data_validation import (
    detect_gaps,
    detect_price_warnings,
    validate_bar,
    validate_bars,
)


def _bar(ts=date(2024, 1, 2), open_=100, high=105, low=99, close=102, volume=1000) -> OHLCVBar:
    return OHLCVBar(
        ts=ts,
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=volume,
    )


def test_validate_bar_accepts_a_well_formed_bar():
    assert validate_bar(_bar()) is None


def test_validate_bar_rejects_non_positive_prices():
    assert validate_bar(_bar(open_=0)) == "non_positive_price"
    assert validate_bar(_bar(close=-5)) == "non_positive_price"


def test_validate_bar_rejects_negative_volume():
    assert validate_bar(_bar(volume=-1)) == "negative_volume"


def test_validate_bar_rejects_low_greater_than_high():
    assert validate_bar(_bar(low=110, high=105)) == "low_greater_than_high"


def test_validate_bar_rejects_open_or_close_outside_high_low_range():
    assert validate_bar(_bar(open_=200, high=105)) == "open_or_close_above_high"
    assert validate_bar(_bar(close=50, low=99)) == "open_or_close_below_low"


def test_validate_bars_splits_valid_from_invalid():
    bars = [_bar(ts=date(2024, 1, 2)), _bar(ts=date(2024, 1, 3), volume=-1)]

    valid, issues = validate_bars(bars)

    assert len(valid) == 1
    assert valid[0].ts == date(2024, 1, 2)
    assert len(issues) == 1
    assert issues[0].reason == "negative_volume"


def test_validate_bars_rejects_duplicate_timestamps_in_the_same_batch():
    bars = [_bar(ts=date(2024, 1, 2)), _bar(ts=date(2024, 1, 2))]

    valid, issues = validate_bars(bars)

    assert len(valid) == 1
    assert issues[0].reason == "duplicate_timestamp_in_batch"


def test_detect_gaps_finds_missing_weekdays():
    bars = [_bar(ts=date(2024, 1, 2)), _bar(ts=date(2024, 1, 5))]  # skips Wed/Thu (1/3, 1/4)

    gaps = detect_gaps(bars)

    assert gaps == [date(2024, 1, 3), date(2024, 1, 4)]


def test_detect_gaps_ignores_weekends():
    # Fri 1/5 -> Mon 1/8: Sat/Sun aren't gaps.
    bars = [_bar(ts=date(2024, 1, 5)), _bar(ts=date(2024, 1, 8))]

    assert detect_gaps(bars) == []


def test_detect_gaps_needs_at_least_two_bars():
    assert detect_gaps([_bar()]) == []
    assert detect_gaps([]) == []


def test_validate_bar_rejects_a_future_timestamp():
    """The explicit Phase 10 adversarial requirement: a bad market-data
    record (here, a not-yet-real trading day) is rejected."""
    tomorrow = date.today() + timedelta(days=1)
    assert validate_bar(_bar(ts=tomorrow)) == "future_timestamp"


def test_validate_bar_accepts_todays_date_as_of_boundary():
    today = date(2024, 6, 15)
    assert validate_bar(_bar(ts=today), as_of=today) is None


def test_validate_bar_as_of_param_controls_the_future_boundary():
    # A date that's "in the future" relative to a pinned earlier as_of,
    # even though it's actually in the past relative to wall-clock today —
    # proves the check uses the passed-in as_of, not always today().
    assert validate_bar(_bar(ts=date(2020, 1, 5)), as_of=date(2020, 1, 1)) == "future_timestamp"


def test_validate_bars_rejects_a_future_dated_bar_in_a_batch():
    bars = [_bar(ts=date(2024, 1, 2)), _bar(ts=date(2024, 1, 3))]
    valid, issues = validate_bars(bars, as_of=date(2024, 1, 2))
    assert len(valid) == 1
    assert valid[0].ts == date(2024, 1, 2)
    assert issues[0].reason == "future_timestamp"


class TestDetectPriceWarnings:
    def test_a_normal_days_move_produces_no_warning(self):
        bars = [_bar(ts=date(2024, 1, 2), close=100), _bar(ts=date(2024, 1, 3), close=102)]
        assert detect_price_warnings(bars) == []

    def test_an_abnormally_large_move_is_flagged_as_a_warning_not_rejected(self):
        """The explicit Phase 10 requirement: distinguish WARNING from
        REJECTED — an abnormal move is flagged, never silently ingested,
        but also never dropped the way a REJECTED bar is."""
        bars = [
            _bar(ts=date(2024, 1, 2), close=100),
            _bar(ts=date(2024, 1, 3), close=200, high=205, low=99),
        ]
        warnings = detect_price_warnings(bars)
        assert len(warnings) == 1
        assert warnings[0].ts == date(2024, 1, 3)
        assert "abnormal_price_move" in warnings[0].reason

        # Never dropped — that's validate_bars' job, not this function's.
        valid, _ = validate_bars(bars, as_of=date(2024, 1, 3))
        assert len(valid) == 2

    def test_a_custom_threshold_is_respected(self):
        bars = [_bar(ts=date(2024, 1, 2), close=100), _bar(ts=date(2024, 1, 3), close=110)]
        assert detect_price_warnings(bars, threshold=0.5) == []
        assert len(detect_price_warnings(bars, threshold=0.05)) == 1

    def test_needs_at_least_two_bars(self):
        assert detect_price_warnings([_bar()]) == []
        assert detect_price_warnings([]) == []
