"""Provider-level tests for `GroqLLMProvider` — mocked at the SDK client
boundary (`self._client.chat.completions.create`), never a real network
call, so this file runs in the standard `pytest` invocation with no
`GROQ_API_KEY` required (Step: "the normal test suite must NOT require
GROQ_API_KEY"). Live-network verification is `tests/integration/
test_agent_live_providers.py`, marked `@pytest.mark.live_llm`.

Responses are built from groq's own real Pydantic response types (not bare
Mocks) so a schema drift in the SDK would show up here as a construction
error, not just at runtime against a real API.
"""

from __future__ import annotations

import httpx
import pytest
from app.agent.llm_provider import (
    GroqLLMProvider,
    LLMMessage,
    LLMProviderError,
    ToolCallRequest,
    ToolDefinition,
)
from groq.types.chat import ChatCompletion
from groq.types.chat.chat_completion import Choice
from groq.types.chat.chat_completion_message import ChatCompletionMessage
from groq.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)
from groq.types.completion_usage import CompletionUsage

_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def _completion(
    *, content: str | None = None, tool_calls: list[ChatCompletionMessageToolCall] | None = None
) -> ChatCompletion:
    message = ChatCompletionMessage(role="assistant", content=content, tool_calls=tool_calls)
    choice = Choice(
        finish_reason="tool_calls" if tool_calls else "stop",
        index=0,
        message=message,
        logprobs=None,
    )
    usage = CompletionUsage(completion_tokens=12, prompt_tokens=34, total_tokens=46)
    return ChatCompletion(
        id="chatcmpl-1", choices=[choice], created=1, model="openai/gpt-oss-20b",
        object="chat.completion", usage=usage,
    )


def _provider() -> GroqLLMProvider:
    return GroqLLMProvider(api_key="fake-not-real", model="openai/gpt-oss-20b", timeout_seconds=5.0)


class TestGroqToolDefinitionConversion:
    def test_tool_definitions_convert_to_openai_style_function_schema(self, monkeypatch):
        provider = _provider()
        captured = {}

        def _fake_create(**kwargs):
            captured.update(kwargs)
            return _completion(content="ok")

        monkeypatch.setattr(provider._client.chat.completions, "create", _fake_create)
        tools = [
            ToolDefinition(name="get_stock_quote", description="d", input_schema={"type": "object"})
        ]

        provider.complete(
            system="sys", messages=[LLMMessage(role="user", content="hi")], tools=tools
        )

        assert captured["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "get_stock_quote",
                    "description": "d",
                    "parameters": {"type": "object"},
                },
            }
        ]

    def test_system_prompt_becomes_the_leading_system_message(self, monkeypatch):
        provider = _provider()
        captured = {}
        monkeypatch.setattr(
            provider._client.chat.completions, "create",
            lambda **kw: captured.update(kw) or _completion(content="ok"),
        )

        provider.complete(
            system="be concise", messages=[LLMMessage(role="user", content="hi")], tools=[]
        )

        assert captured["messages"][0] == {"role": "system", "content": "be concise"}


class TestGroqResponseParsing:
    def test_a_text_only_response_has_no_tool_calls(self, monkeypatch):
        provider = _provider()
        monkeypatch.setattr(
            provider._client.chat.completions,
            "create",
            lambda **kw: _completion(content="the answer"),
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.content == "the answer"
        assert response.tool_calls == ()
        assert response.usage.input_tokens == 34
        assert response.usage.output_tokens == 12

    def test_a_tool_call_response_is_converted_to_tool_call_request(self, monkeypatch):
        provider = _provider()
        tool_call = ChatCompletionMessageToolCall(
            id="call_1", type="function",
            function=Function(name="get_stock_quote", arguments='{"ticker": "AAPL"}'),
        )
        monkeypatch.setattr(
            provider._client.chat.completions, "create",
            lambda **kw: _completion(tool_calls=[tool_call]),
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.tool_calls == (
            ToolCallRequest(id="call_1", name="get_stock_quote", arguments={"ticker": "AAPL"}),
        )

    def test_malformed_tool_call_arguments_degrade_to_an_empty_dict_not_a_crash(self, monkeypatch):
        provider = _provider()
        tool_call = ChatCompletionMessageToolCall(
            id="call_1", type="function",
            function=Function(name="get_stock_quote", arguments="{not valid json"),
        )
        monkeypatch.setattr(
            provider._client.chat.completions, "create",
            lambda **kw: _completion(tool_calls=[tool_call]),
        )

        response = provider.complete(system="sys", messages=[], tools=[])

        assert response.tool_calls[0].arguments == {}


class TestGroqErrorMapping:
    def test_authentication_error_maps_to_llm_provider_error(self, monkeypatch):
        import groq

        provider = _provider()
        response = httpx.Response(
            401, request=_REQUEST, json={"error": {"message": "invalid api key"}}
        )
        exc = groq.AuthenticationError("invalid api key", response=response, body=None)

        def _raise(**kw):
            raise exc

        monkeypatch.setattr(provider._client.chat.completions, "create", _raise)

        with pytest.raises(LLMProviderError):
            provider.complete(system="sys", messages=[], tools=[])

    def test_rate_limit_error_maps_to_llm_provider_error(self, monkeypatch):
        import groq

        provider = _provider()
        response = httpx.Response(
            429, request=_REQUEST, json={"error": {"message": "rate limited"}}
        )
        exc = groq.RateLimitError("rate limited", response=response, body=None)
        monkeypatch.setattr(
            provider._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError):
            provider.complete(system="sys", messages=[], tools=[])

    def test_timeout_maps_to_llm_provider_error(self, monkeypatch):
        import groq

        provider = _provider()
        exc = groq.APITimeoutError(_REQUEST)
        monkeypatch.setattr(
            provider._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError, match="timed out"):
            provider.complete(system="sys", messages=[], tools=[])

    def test_llm_provider_error_never_leaks_the_api_key(self, monkeypatch):
        """The api key isn't in these exceptions at all in practice, but
        this guards the actual contract: whatever the SDK raises, our own
        error message must never be built by echoing back request
        headers/credentials — only the SDK's own safe `str(exc)`."""
        import groq

        provider = GroqLLMProvider(api_key="sk-super-secret-value", model="m", timeout_seconds=5.0)
        response = httpx.Response(
            401, request=_REQUEST, json={"error": {"message": "invalid api key"}}
        )
        exc = groq.AuthenticationError("invalid api key", response=response, body=None)
        monkeypatch.setattr(
            provider._client.chat.completions, "create", lambda **kw: (_ for _ in ()).throw(exc)
        )

        with pytest.raises(LLMProviderError) as exc_info:
            provider.complete(system="sys", messages=[], tools=[])

        assert "sk-super-secret-value" not in str(exc_info.value)


class TestGroqProviderIdentity:
    def test_reports_its_own_provider_name_and_model(self):
        provider = GroqLLMProvider(api_key="fake", model="openai/gpt-oss-120b", timeout_seconds=5.0)
        assert provider.provider_name == "groq"
        assert provider.model == "openai/gpt-oss-120b"

    def test_never_declares_any_built_in_groq_tool(self, monkeypatch):
        """Structural check for the explicit non-goal: only AlphaLens's own
        function tools are ever declared — never one of Groq's built-in,
        server-side tools (web search, code execution)."""
        provider = _provider()
        captured = {}
        monkeypatch.setattr(
            provider._client.chat.completions, "create",
            lambda **kw: captured.update(kw) or _completion(content="ok"),
        )
        tools = [ToolDefinition(name="get_news", description="d", input_schema={"type": "object"})]

        provider.complete(system="sys", messages=[], tools=tools)

        for tool in captured["tools"]:
            assert tool["type"] == "function"
            assert "function" in tool
