"""Provider-level tests for `GeminiLLMProvider` — mocked at the SDK client
boundary (`self._client.models.generate_content`), never a real network
call, so this file runs in the standard `pytest` invocation with no
`GEMINI_API_KEY` required. Live-network verification is
`tests/integration/test_agent_live_providers.py`, marked
`@pytest.mark.live_llm`.

Responses are built from google-genai's own real Pydantic response types
(not bare Mocks) so a schema drift in the SDK would show up here as a
construction error, not just at runtime against a real API.
"""

from __future__ import annotations

import pytest
from app.agent.llm_provider import (
    GeminiLLMProvider,
    LLMMessage,
    LLMProviderError,
    ToolCallRequest,
    ToolDefinition,
    _to_gemini_contents,
)
from google.genai import types


def _response(
    *, text: str | None = None, function_calls: list[types.FunctionCall] | None = None
) -> types.GenerateContentResponse:
    parts = []
    if text is not None:
        parts.append(types.Part(text=text))
    for call in function_calls or []:
        parts.append(types.Part(function_call=call))
    content = types.Content(role="model", parts=parts)
    candidate = types.Candidate(content=content, finish_reason=types.FinishReason.STOP, index=0)
    usage = types.GenerateContentResponseUsageMetadata(
        prompt_token_count=34, candidates_token_count=12, total_token_count=46
    )
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def _provider() -> GeminiLLMProvider:
    return GeminiLLMProvider(
        api_key="fake-not-real", model="gemini-flash-latest", timeout_seconds=5.0
    )


class TestGeminiMessageConversion:
    """Regression coverage for a real bug found during Phase 8.5 live
    validation: a live call using `role="tool"` for the function-response
    turn failed with a real `400 INVALID_ARGUMENT` from the actual Gemini
    API — `Role 'tool' is not supported`. The classic `generate_content` +
    manual `contents` surface only accepts `user`/`model` (among others,
    but never `tool`) — see ADR-034."""

    def test_a_tool_result_turn_uses_role_user_not_role_tool(self):
        messages = [
            LLMMessage(
                role="tool",
                content='{"result": "ok"}',
                tool_call_id="call_1",
                tool_name="get_stock_quote",
            )
        ]

        contents = _to_gemini_contents(messages, types)

        assert len(contents) == 1
        assert contents[0].role == "user"
        assert contents[0].role != "tool"
        assert contents[0].parts[0].function_response.name == "get_stock_quote"

    def test_an_assistant_tool_call_turn_uses_role_model(self):
        messages = [
            LLMMessage(
                role="assistant",
                tool_calls=(
                    ToolCallRequest(
                        id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}
                    ),
                ),
            )
        ]

        contents = _to_gemini_contents(messages, types)

        assert contents[0].role == "model"


class TestGeminiToolDefinitionConversion:
    def test_tool_definitions_convert_to_a_single_tool_with_function_declarations(
        self, monkeypatch
    ):
        provider = _provider()
        captured = {}

        def _fake_generate_content(**kwargs):
            captured.update(kwargs)
            return _response(text="ok")

        monkeypatch.setattr(provider._client.models, "generate_content", _fake_generate_content)
        tools = [
            ToolDefinition(name="get_stock_quote", description="d", input_schema={"type": "object"})
        ]

        provider.complete(
            system="sys", messages=[LLMMessage(role="user", content="hi")], tools=tools
        )

        config = captured["config"]
        assert len(config.tools) == 1
        declarations = config.tools[0].function_declarations
        assert len(declarations) == 1
        assert declarations[0].name == "get_stock_quote"
        assert declarations[0].description == "d"
        assert declarations[0].parameters_json_schema == {"type": "object"}

    def test_system_prompt_goes_to_system_instruction_not_contents(self, monkeypatch):
        provider = _provider()
        captured = {}
        monkeypatch.setattr(
            provider._client.models, "generate_content",
            lambda **kw: captured.update(kw) or _response(text="ok"),
        )

        provider.complete(
            system="be concise", messages=[LLMMessage(role="user", content="hi")], tools=[]
        )

        assert captured["config"].system_instruction == "be concise"
        assert all(c.role != "system" for c in captured["contents"])

    def test_automatic_function_calling_is_always_disabled(self, monkeypatch):
        """The orchestrator owns the tool-calling loop for every provider
        identically — Gemini's SDK-side auto-execution must never run."""
        provider = _provider()
        captured = {}
        monkeypatch.setattr(
            provider._client.models, "generate_content",
            lambda **kw: captured.update(kw) or _response(text="ok"),
        )

        provider.complete(system="sys", messages=[], tools=[])

        assert captured["config"].automatic_function_calling.disable is True

    def test_never_enables_a_built_in_gemini_tool(self, monkeypatch):
        provider = _provider()
        captured = {}
        monkeypatch.setattr(
            provider._client.models, "generate_content",
            lambda **kw: captured.update(kw) or _response(text="ok"),
        )
        tools = [ToolDefinition(name="get_news", description="d", input_schema={"type": "object"})]

        provider.complete(system="sys", messages=[], tools=tools)

        tool = captured["config"].tools[0]
        assert tool.google_search is None
        assert tool.code_execution is None
        assert tool.computer_use is None
        assert tool.function_declarations is not None


class TestGeminiResponseParsing:
    def test_a_text_only_response_has_no_tool_calls(self, monkeypatch):
        provider = _provider()
        monkeypatch.setattr(
            provider._client.models, "generate_content", lambda **kw: _response(text="the answer")
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.content == "the answer"
        assert response.tool_calls == ()
        assert response.usage.input_tokens == 34
        assert response.usage.output_tokens == 12

    def test_a_function_call_response_is_converted_to_tool_call_request(self, monkeypatch):
        provider = _provider()
        call = types.FunctionCall(id="call_1", name="get_stock_quote", args={"ticker": "AAPL"})
        monkeypatch.setattr(
            provider._client.models, "generate_content",
            lambda **kw: _response(function_calls=[call]),
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.tool_calls == (
            ToolCallRequest(id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}),
        )

    def test_a_function_call_with_no_id_gets_a_synthesized_one(self, monkeypatch):
        """Unlike Anthropic/Groq's OpenAI-style APIs, Gemini's `id` on a
        function call is documented as optional — this must never produce
        an empty/None id in our internal ToolCallRequest."""
        provider = _provider()
        call = types.FunctionCall(id=None, name="get_stock_quote", args={"ticker": "AAPL"})
        monkeypatch.setattr(
            provider._client.models, "generate_content",
            lambda **kw: _response(function_calls=[call]),
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.tool_calls[0].id
        assert response.tool_calls[0].id != "None"


class TestGeminiErrorMapping:
    def test_client_error_maps_to_llm_provider_error(self, monkeypatch):
        from google.genai import errors

        provider = _provider()
        exc = errors.ClientError(401, {"error": {"message": "invalid api key"}})
        monkeypatch.setattr(
            provider._client.models, "generate_content", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError):
            provider.complete(system="sys", messages=[], tools=[])

    def test_rate_limit_status_maps_to_llm_provider_error(self, monkeypatch):
        from google.genai import errors

        provider = _provider()
        exc = errors.ClientError(429, {"error": {"message": "rate limited"}})
        monkeypatch.setattr(
            provider._client.models, "generate_content", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError):
            provider.complete(system="sys", messages=[], tools=[])

    def test_server_error_maps_to_llm_provider_error(self, monkeypatch):
        from google.genai import errors

        provider = _provider()
        exc = errors.ServerError(503, {"error": {"message": "unavailable"}})
        monkeypatch.setattr(
            provider._client.models, "generate_content", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError):
            provider.complete(system="sys", messages=[], tools=[])

    def test_an_unexpected_transport_exception_never_escapes_unwrapped(self, monkeypatch):
        """The SDK has no dedicated timeout class (unlike anthropic/groq) —
        this is the scenario that gap requires a broad catch for."""
        provider = _provider()

        def _raise(**kw):
            raise TimeoutError("connection timed out")

        monkeypatch.setattr(provider._client.models, "generate_content", _raise)

        with pytest.raises(LLMProviderError, match="failed"):
            provider.complete(system="sys", messages=[], tools=[])

    def test_a_safety_blocked_response_raises_rather_than_returning_an_empty_answer(
        self, monkeypatch
    ):
        provider = _provider()
        blocked = types.GenerateContentResponse(
            candidates=[],
            prompt_feedback=types.GenerateContentResponsePromptFeedback(
                block_reason=types.BlockedReason.SAFETY
            ),
        )
        monkeypatch.setattr(provider._client.models, "generate_content", lambda **kw: blocked)

        with pytest.raises(LLMProviderError, match="blocked"):
            provider.complete(system="sys", messages=[], tools=[])

    def test_llm_provider_error_never_leaks_the_api_key(self, monkeypatch):
        from google.genai import errors

        provider = GeminiLLMProvider(
            api_key="sk-super-secret-value", model="m", timeout_seconds=5.0
        )
        exc = errors.ClientError(401, {"error": {"message": "invalid api key"}})
        monkeypatch.setattr(
            provider._client.models, "generate_content", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(system="sys", messages=[], tools=[])

        assert "sk-super-secret-value" not in str(exc_info.value)


class TestGeminiProviderIdentity:
    def test_reports_its_own_provider_name_and_model(self):
        provider = GeminiLLMProvider(api_key="fake", model="gemini-3-flash", timeout_seconds=5.0)
        assert provider.provider_name == "gemini"
        assert provider.model == "gemini-3-flash"
