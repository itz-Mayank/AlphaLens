"""Integration tests for `app/services/prediction_service.py` against real
Postgres and real (demo-provider) price bars — the
PREDICTION -> FUTURE OBSERVATION -> REALIZED OUTCOME -> ERROR pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models.job import JobType
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.repositories.prediction_repository import PredictionRepository
from app.repositories.price_bar_repository import PriceBarRepository
from app.services import prediction_service
from app.services.market_data_service import run_ingestion


def _seed_security(db_session, ticker="AAPL") -> Security:
    security = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers, lookback_days=200) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


class TestLogPrediction:
    def test_logs_a_prediction_with_the_exact_model_version_that_produced_it(self, db_session):
        """The explicit Phase 10 adversarial scenario: a prediction
        references the registered model version, not just a model name."""
        security = _seed_security(db_session)
        as_of = datetime.now(UTC).date()
        prediction_service.log_prediction(
            db_session,
            security_id=security.id,
            model_type="xgboost_return",
            model_version="xgboost_return-20260101T000000Z",
            feature_version="fs_v1",
            as_of_date=as_of,
            horizon_days=5,
            predicted_return=Decimal("0.01"),
            predicted_class=None,
            predicted_probabilities=None,
            prediction_timestamp=datetime.now(UTC),
        )
        unevaluated = PredictionRepository(db_session).list_unevaluated()
        assert len(unevaluated) == 1
        assert unevaluated[0].model_version == "xgboost_return-20260101T000000Z"
        assert unevaluated[0].security_id == security.id


class TestEvaluateMaturedPredictions:
    def test_an_unmatured_prediction_is_not_scored(self, db_session):
        """The explicit Phase 10 adversarial scenario: unmatured
        predictions are not scored."""
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=10)
        bars = sorted(
            PriceBarRepository(db_session).get_range(security_id=security.id, start=None, end=None),
            key=lambda b: b.ts,
        )
        # A horizon far beyond the available history — can never mature.
        prediction_service.log_prediction(
            db_session,
            security_id=security.id,
            model_type="xgboost_return",
            model_version="v1",
            feature_version="fs_v1",
            as_of_date=bars[0].ts.date(),
            horizon_days=1000,
            predicted_return=Decimal("0.01"),
            predicted_class=None,
            predicted_probabilities=None,
            prediction_timestamp=datetime.now(UTC),
        )
        summary = prediction_service.evaluate_matured_predictions(db_session)
        assert summary.evaluated == 0
        assert summary.still_unmatured == 1
        assert PredictionRepository(db_session).list_evaluated(model_type="xgboost_return") == []

    def test_a_matured_prediction_is_scored_against_the_correct_real_future_bar(self, db_session):
        """The explicit Phase 10 adversarial scenario: matured predictions
        are evaluated against correct future observations — checked here
        against the real ingested bars, not a hardcoded expected number."""
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        bars = sorted(
            PriceBarRepository(db_session).get_range(security_id=security.id, start=None, end=None),
            key=lambda b: b.ts,
        )
        assert len(bars) > 20
        as_of_bar = bars[5]
        horizon_days = 5
        future_bar = bars[5 + horizon_days]
        expected_realized_return = (future_bar.close - as_of_bar.close) / as_of_bar.close

        prediction_service.log_prediction(
            db_session,
            security_id=security.id,
            model_type="xgboost_return",
            model_version="v1",
            feature_version="fs_v1",
            as_of_date=as_of_bar.ts.date(),
            horizon_days=horizon_days,
            predicted_return=Decimal("0.01"),
            predicted_class=None,
            predicted_probabilities=None,
            prediction_timestamp=datetime.now(UTC),
        )

        summary = prediction_service.evaluate_matured_predictions(db_session)
        assert summary.evaluated == 1

        evaluated = PredictionRepository(db_session).list_evaluated(model_type="xgboost_return")
        assert len(evaluated) == 1
        # The `predictions.realized_return` column is NUMERIC(10, 6) —
        # compare at that same precision, not against the unrounded
        # Decimal division result.
        assert evaluated[0].realized_return == expected_realized_return.quantize(
            Decimal("0.000001")
        )
        assert evaluated[0].evaluated_at is not None

    def test_running_evaluation_twice_never_double_scores_the_same_prediction(self, db_session):
        """The explicit Phase 10 adversarial scenario: Celery retry (or
        simply two evaluation cycles) does not duplicate state — an
        already-evaluated prediction is never re-evaluated or double
        counted."""
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        bars = sorted(
            PriceBarRepository(db_session).get_range(security_id=security.id, start=None, end=None),
            key=lambda b: b.ts,
        )
        prediction_service.log_prediction(
            db_session,
            security_id=security.id,
            model_type="xgboost_return",
            model_version="v1",
            feature_version="fs_v1",
            as_of_date=bars[0].ts.date(),
            horizon_days=3,
            predicted_return=Decimal("0.0"),
            predicted_class=None,
            predicted_probabilities=None,
            prediction_timestamp=datetime.now(UTC),
        )

        first = prediction_service.evaluate_matured_predictions(db_session)
        second = prediction_service.evaluate_matured_predictions(db_session)

        assert first.evaluated == 1
        assert second.evaluated == 0  # nothing left unevaluated to (re-)score
        evaluated = PredictionRepository(db_session).list_evaluated(model_type="xgboost_return")
        assert len(evaluated) == 1


class TestGetLivePerformance:
    def test_reports_insufficient_data_when_nothing_has_matured_yet(self, db_session):
        report = prediction_service.get_live_performance(db_session, model_type="xgboost_return")
        assert report.insufficient_data is True
        assert report.sample_count == 0

    def test_computes_real_mae_from_matured_return_predictions(self, db_session):
        security = _seed_security(db_session)
        _ingest_prices(db_session, [security.ticker], lookback_days=200)
        bars = sorted(
            PriceBarRepository(db_session).get_range(security_id=security.id, start=None, end=None),
            key=lambda b: b.ts,
        )
        as_of_bar = bars[5]
        future_bar = bars[10]
        realized_return = (future_bar.close - as_of_bar.close) / as_of_bar.close
        # A deliberately-wrong prediction so MAE is provably nonzero and
        # provably equal to |predicted - realized|.
        predicted_return = realized_return + Decimal("0.05")

        prediction_service.log_prediction(
            db_session,
            security_id=security.id,
            model_type="xgboost_return",
            model_version="v1",
            feature_version="fs_v1",
            as_of_date=as_of_bar.ts.date(),
            horizon_days=5,
            predicted_return=predicted_return,
            predicted_class=None,
            predicted_probabilities=None,
            prediction_timestamp=datetime.now(UTC),
        )
        prediction_service.evaluate_matured_predictions(db_session)

        report = prediction_service.get_live_performance(db_session, model_type="xgboost_return")
        assert report.insufficient_data is False
        assert report.sample_count == 1
        assert report.mae is not None
        assert abs(report.mae - 0.05) < 1e-6

    def test_never_mixes_live_performance_with_training_backtest_metrics(self, db_session):
        """The report's own disclaimer makes the distinction explicit —
        this test just pins that the disclaimer field exists and says so,
        since there is no shared code path with ml.registry's stored
        metrics to accidentally conflate."""
        report = prediction_service.get_live_performance(db_session, model_type="xgboost_return")
        assert "not this model's training/backtest metrics" in report.disclaimer
