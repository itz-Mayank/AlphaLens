from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.dashboard_service import compute_freshness_status, compute_return_percent

DAY2 = datetime(2024, 1, 10, tzinfo=UTC)


class TestComputeReturnPercent:
    def test_positive_return(self):
        assert compute_return_percent(Decimal(110), Decimal(100)) == Decimal("10.000000")

    def test_negative_return(self):
        assert compute_return_percent(Decimal(90), Decimal(100)) == Decimal("-10.000000")

    def test_zero_return(self):
        assert compute_return_percent(Decimal(100), Decimal(100)) == Decimal("0.000000")

    def test_none_when_no_previous_close(self):
        assert compute_return_percent(Decimal(100), None) is None

    def test_none_when_previous_close_is_zero(self):
        """A percent change against a zero base is undefined — never
        rendered as 0% or an error, just "no defined return"."""
        assert compute_return_percent(Decimal(100), Decimal(0)) is None


class TestComputeFreshnessStatus:
    def test_none_is_no_data(self):
        assert compute_freshness_status(None, now=DAY2) == "no_data"

    def test_within_current_threshold(self):
        assert compute_freshness_status(DAY2, now=DAY2 + timedelta(days=2)) == "current"

    def test_boundary_at_exactly_current_threshold_is_current(self):
        assert compute_freshness_status(DAY2, now=DAY2 + timedelta(days=3)) == "current"

    def test_just_past_current_threshold_is_stale(self):
        assert compute_freshness_status(DAY2, now=DAY2 + timedelta(days=3, seconds=1)) == "stale"

    def test_within_stale_threshold(self):
        assert compute_freshness_status(DAY2, now=DAY2 + timedelta(days=10)) == "stale"

    def test_past_stale_threshold_is_outdated(self):
        assert compute_freshness_status(DAY2, now=DAY2 + timedelta(days=30)) == "outdated"

    def test_a_stale_reading_taken_before_the_latest_bar_is_still_current(self):
        """`now` can be earlier than `latest_ts` in principle (clock skew,
        or a caller passing a fixed `now` for testing) — age is clamped by
        construction (negative age is still <= the current threshold), so
        this never produces a nonsensical negative-age status."""
        assert compute_freshness_status(DAY2, now=DAY2 - timedelta(days=1)) == "current"
