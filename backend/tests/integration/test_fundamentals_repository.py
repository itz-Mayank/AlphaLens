from datetime import UTC, date, datetime
from decimal import Decimal

from app.db.models.security import Security
from app.providers.base import CompanyFactsResult, FundamentalFact
from app.repositories.fundamentals_repository import FundamentalsRepository


def _security(db_session, ticker: str = "AAPL") -> Security:
    s = Security(ticker=ticker, name=f"{ticker} Inc.", exchange="NASDAQ", data_source="demo")
    db_session.add(s)
    db_session.flush()
    return s


def _fact(
    concept: str, value: int, period_end: date, filed_date: date, form: str = "10-K"
) -> FundamentalFact:
    return FundamentalFact(
        concept=concept,
        value=Decimal(value),
        unit="USD",
        period_start=None,
        period_end=period_end,
        fiscal_year=period_end.year,
        fiscal_period="FY",
        form=form,
        filed_date=filed_date,
        accession_number="0000320193-23-000106",
    )


def test_upsert_facts_is_idempotent_on_the_natural_identity(db_session):
    security = _security(db_session)
    result = CompanyFactsResult(
        ticker="AAPL",
        company_name="Apple Inc.",
        external_id="CIK0000320193",
        facts=[_fact("Assets", 100, date(2023, 9, 30), date(2023, 11, 3))],
        retrieved_at=datetime.now(UTC),
    )
    repo = FundamentalsRepository(db_session)

    written_first = repo.upsert_facts(
        security_id=security.id, result=result, source="SECEdgarFundamentalsProvider",
        retrieved_at=datetime.now(UTC),
    )
    written_second = repo.upsert_facts(
        security_id=security.id, result=result, source="SECEdgarFundamentalsProvider",
        retrieved_at=datetime.now(UTC),
    )

    assert written_first == 1
    assert written_second == 1  # re-ingest updates, never duplicates
    rows = repo.get_latest_by_concept(security_id=security.id)
    assert len(rows) == 1


def test_a_revised_value_for_the_same_filing_overwrites_not_duplicates(db_session):
    security = _security(db_session)
    repo = FundamentalsRepository(db_session)

    original = CompanyFactsResult(
        ticker="AAPL", company_name="Apple Inc.", external_id="CIK0000320193",
        facts=[_fact("Assets", 100, date(2023, 9, 30), date(2023, 11, 3))],
        retrieved_at=datetime.now(UTC),
    )
    repo.upsert_facts(
        security_id=security.id, result=original, source="SECEdgarFundamentalsProvider",
        retrieved_at=datetime.now(UTC),
    )

    revised = CompanyFactsResult(
        ticker="AAPL", company_name="Apple Inc.", external_id="CIK0000320193",
        facts=[_fact("Assets", 999, date(2023, 9, 30), date(2023, 11, 3))],
        retrieved_at=datetime.now(UTC),
    )
    repo.upsert_facts(
        security_id=security.id, result=revised, source="SECEdgarFundamentalsProvider",
        retrieved_at=datetime.now(UTC),
    )

    [row] = repo.get_latest_by_concept(security_id=security.id)
    assert row.value == Decimal(999)


def test_get_latest_by_concept_picks_the_most_recent_period_per_concept(db_session):
    security = _security(db_session)
    repo = FundamentalsRepository(db_session)
    result = CompanyFactsResult(
        ticker="AAPL", company_name="Apple Inc.", external_id="CIK0000320193",
        facts=[
            _fact("Assets", 100, date(2022, 9, 24), date(2022, 10, 28)),
            _fact("Assets", 200, date(2023, 9, 30), date(2023, 11, 3)),
        ],
        retrieved_at=datetime.now(UTC),
    )
    repo.upsert_facts(
        security_id=security.id, result=result, source="SECEdgarFundamentalsProvider",
        retrieved_at=datetime.now(UTC),
    )

    [row] = repo.get_latest_by_concept(security_id=security.id)
    assert row.value == Decimal(200)
    assert row.period_end == date(2023, 9, 30)


def test_facts_are_scoped_per_security(db_session):
    apple = _security(db_session, "AAPL")
    msft = _security(db_session, "MSFT")
    repo = FundamentalsRepository(db_session)

    repo.upsert_facts(
        security_id=apple.id,
        result=CompanyFactsResult(
            ticker="AAPL", company_name="Apple Inc.", external_id="CIK1",
            facts=[_fact("Assets", 1, date(2023, 9, 30), date(2023, 11, 3))],
            retrieved_at=datetime.now(UTC),
        ),
        source="SECEdgarFundamentalsProvider", retrieved_at=datetime.now(UTC),
    )

    assert len(repo.get_latest_by_concept(security_id=apple.id)) == 1
    assert len(repo.get_latest_by_concept(security_id=msft.id)) == 0
