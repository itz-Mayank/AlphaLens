"""API tests for `POST /api/v1/research/chat`. The real LLM call is
replaced with a scripted `FakeLLMProvider` via monkeypatching
`app.services.agent_chat_service.get_llm_provider` — the same convention
used elsewhere in this suite for swapping out an external dependency
(e.g. `ingest_market_data_task.delay`). Everything else (auth, DB,
tools, evidence assembly, rate limiting) runs for real.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.agent.llm_provider import FakeLLMProvider, LLMResponse, ToolCallRequest
from app.db.models.job import JobType
from app.db.models.security import Security
from app.repositories.job_repository import JobRepository
from app.services.market_data_service import run_ingestion


def _seed_security(db_session, ticker: str = "AAPL", name: str = "Apple Inc.") -> Security:
    security = Security(ticker=ticker, name=name, exchange="NASDAQ", data_source="demo")
    db_session.add(security)
    db_session.flush()
    return security


def _ingest_prices(db_session, tickers: list[str], *, lookback_days: int = 60) -> None:
    end = datetime.now(UTC).date()
    start = end - timedelta(days=lookback_days)
    job = JobRepository(db_session).create(
        job_type=JobType.MARKET_DATA_INGESTION, requested_by_user_id=None
    )
    db_session.flush()
    run_ingestion(db_session, job_id=job.id, tickers=tickers, start_date=start, end_date=end)
    db_session.flush()


def _final(text: str) -> LLMResponse:
    return LLMResponse(content=text, tool_calls=(), stop_reason="end_turn")


def _tool_call_response(*calls: ToolCallRequest) -> LLMResponse:
    return LLMResponse(content=None, tool_calls=tuple(calls), stop_reason="tool_use")


def _stub_provider(monkeypatch, fake: FakeLLMProvider) -> None:
    monkeypatch.setattr("app.services.agent_chat_service.get_llm_provider", lambda: fake)


def test_chat_requires_authentication(client):
    res = client.post("/api/v1/research/chat", json={"message": "What's AAPL's price?"})
    assert res.status_code == 401


def test_chat_rejects_an_empty_message(client, auth_headers):
    res = client.post("/api/v1/research/chat", json={"message": ""}, headers=auth_headers)
    assert res.status_code == 422


def test_chat_rejects_an_oversized_message(client, auth_headers):
    res = client.post(
        "/api/v1/research/chat", json={"message": "x" * 2001}, headers=auth_headers
    )
    assert res.status_code == 422


def test_chat_returns_503_when_no_llm_credentials_are_configured(client, auth_headers):
    # No monkeypatching here: exercises the real `get_llm_provider()` registry
    # with the test env's unset LLM_API_KEY (Step: unavailable, never a silent fallback).
    res = client.post(
        "/api/v1/research/chat", json={"message": "What's AAPL's price?"}, headers=auth_headers
    )
    assert res.status_code == 503
    assert res.json()["error"]["code"] == "AGENT_UNAVAILABLE"


def test_full_chat_flow_returns_well_formed_evidence_and_citations(
    client, auth_headers, db_session, monkeypatch
):
    _seed_security(db_session)
    _ingest_prices(db_session, ["AAPL"])
    fake = FakeLLMProvider(
        [
            _tool_call_response(
                ToolCallRequest(id="c1", name="get_stock_quote", arguments={"ticker": "AAPL"})
            ),
            _final("AAPL is trading near its latest close. [Market Data]"),
        ]
    )
    _stub_provider(monkeypatch, fake)

    res = client.post(
        "/api/v1/research/chat", json={"message": "What's AAPL's price?"}, headers=auth_headers
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answer"] == "AAPL is trading near its latest close. [Market Data]"
    assert body["tools_used"] == ["get_stock_quote"]
    assert body["citations"] == ["[Market Data]"]
    assert len(body["evidence"]) == 1
    evidence = body["evidence"][0]
    assert evidence["source_type"] == "MARKET_DATA"
    assert evidence["ticker"] == "AAPL"
    assert len(body["tool_calls"]) == 1
    assert body["tool_calls"][0]["ok"] is True
    assert body["model"] == "fake-model-v1"
    assert body["provider"] == "fake"
    assert body["conversation_id"]
    assert body["request_id"]
    assert body["prompt_version"] == "v1"
    assert "not financial advice" in body["disclaimer"].lower()
    # Never expose chain-of-thought — only the final answer text.
    assert "content" not in body
    assert "reasoning" not in body


def test_conversation_id_round_trips_across_two_requests(
    client, auth_headers, db_session, monkeypatch
):
    _seed_security(db_session)
    _ingest_prices(db_session, ["AAPL"])

    fake_1 = FakeLLMProvider(
        [
            _tool_call_response(
                ToolCallRequest(id="c1", name="get_stock_quote", arguments={"ticker": "AAPL"})
            ),
            _final("AAPL is trading near its latest close. [Market Data]"),
        ]
    )
    _stub_provider(monkeypatch, fake_1)
    first = client.post(
        "/api/v1/research/chat", json={"message": "What's AAPL's price?"}, headers=auth_headers
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    fake_2 = FakeLLMProvider([_final("Following up on AAPL, nothing material has changed.")])
    _stub_provider(monkeypatch, fake_2)
    second = client.post(
        "/api/v1/research/chat",
        json={"message": "Anything new?", "conversation_id": conversation_id},
        headers=auth_headers,
    )

    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] == conversation_id
    # The second call's LLM request should include the first turn's history.
    first_call_messages = fake_2.calls[0]["messages"]
    texts = " ".join(m.content for m in first_call_messages if m.content)
    assert "What's AAPL's price?" in texts
    assert "AAPL is trading near its latest close" in texts


def test_cross_user_isolation_at_the_http_level(
    client, auth_headers, make_user_with_role, db_session, monkeypatch
):
    _seed_security(db_session)
    _ingest_prices(db_session, ["AAPL"])
    shared_conversation_id = "guessed-shared-id"

    fake_alice = FakeLLMProvider(
        [
            _tool_call_response(
                ToolCallRequest(id="c1", name="get_stock_quote", arguments={"ticker": "AAPL"})
            ),
            _final("Alice, AAPL is trading near its latest close."),
        ]
    )
    _stub_provider(monkeypatch, fake_alice)
    alice_res = client.post(
        "/api/v1/research/chat",
        json={
            "message": "What's AAPL's price? This is Alice's private question.",
            "conversation_id": shared_conversation_id,
        },
        headers=auth_headers,
    )
    assert alice_res.status_code == 200, alice_res.text

    bob_headers = make_user_with_role("USER")
    fake_bob = FakeLLMProvider([_final("I have no prior context with you.")])
    _stub_provider(monkeypatch, fake_bob)
    bob_res = client.post(
        "/api/v1/research/chat",
        json={"message": "What did I just ask?", "conversation_id": shared_conversation_id},
        headers=bob_headers,
    )

    assert bob_res.status_code == 200, bob_res.text
    bob_first_call_messages = fake_bob.calls[0]["messages"]
    bob_visible_text = " ".join(m.content for m in bob_first_call_messages if m.content)
    assert "Alice's private question" not in bob_visible_text
    assert "What did I just ask?" in bob_visible_text


def test_rate_limit_is_enforced(client, auth_headers, db_session, monkeypatch):
    # 20/hour (app/api/v1/research.py) — the 21st call in the same window
    # from the same client should be rejected before it ever reaches the
    # (stubbed) LLM provider.
    fake = FakeLLMProvider([_final("ok")] * 20)
    _stub_provider(monkeypatch, fake)

    for _ in range(20):
        res = client.post(
            "/api/v1/research/chat", json={"message": "Hello"}, headers=auth_headers
        )
        assert res.status_code == 200, res.text

    res = client.post("/api/v1/research/chat", json={"message": "Hello"}, headers=auth_headers)
    assert res.status_code == 429
    # The app's standard {"error": {"code", "message"}} envelope must be
    # preserved for a 429 too — slowapi's own default handler instead
    # returns a bare {"error": "<string>"}, which every client's error
    # parsing (reading error.code/error.message) silently mis-reads as an
    # UNKNOWN_ERROR with no message. See app/main.py.
    body = res.json()
    assert isinstance(body["error"], dict)
    assert body["error"]["code"] == "HTTP_ERROR"
    assert "per" in body["error"]["message"]
