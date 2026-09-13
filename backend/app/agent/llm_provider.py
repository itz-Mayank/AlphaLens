"""LLM provider abstraction. The research agent (`app/agent/orchestrator.py`)
depends on this ABC only, never on a concrete vendor SDK — swapping
providers/models is a registry change (`get_llm_provider()`), not a change
to the orchestrator. Same pattern as `MarketDataProvider`/`NewsProvider`
(ADR-002).

Four implementations: `AnthropicLLMProvider`, `GroqLLMProvider`,
`GeminiLLMProvider` (real, `LLM_PROVIDER`-selected — Phase 8.5 added the
latter two without changing this module's contract or the orchestrator at
all), and `FakeLLMProvider` (deterministic, used by the entire test suite
so it never needs real credentials). Every real provider converts the same
vendor-agnostic `LLMMessage`/`ToolDefinition`/`ToolCallRequest` types to
and from its own wire format internally — the orchestrator never sees a
vendor-specific shape.

**The LLM is a reasoning component only.** It decides which tool to call
and synthesizes a final answer from tool results; it never computes a
financial metric itself. Every number in an agent response traces back to
a tool's structured output (`ml.inference`/`ml.backtest`/`ml.nlp`/a
repository query), never the model's own arithmetic — see
`app/agent/tools.py`.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema, e.g. a Pydantic model's `.model_json_schema()`


@dataclass(frozen=True)
class ToolCallRequest:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMMessage:
    """`role`: `"user"` | `"assistant"` | `"tool"`. A `"tool"` message
    carries `tool_call_id`/`tool_name` and its `content` is the tool's
    (already-serialized) result — see `orchestrator.py`."""

    role: str
    content: str | None = None
    tool_calls: tuple[ToolCallRequest, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    content: str | None
    tool_calls: tuple[ToolCallRequest, ...]
    stop_reason: str
    usage: TokenUsage | None = None


class LLMProviderError(Exception):
    """Raised for any provider-side failure (timeout, API error, malformed
    response, missing credentials) — the orchestrator/API layer catches
    this and returns a controlled error, never a raw SDK exception or
    stack trace."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """One request/response turn. Raises `LLMProviderError` on
        timeout/API failure/malformed response — never fabricates a
        response to keep the caller happy."""

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...


def _to_anthropic_messages(messages: list[LLMMessage]) -> list[dict]:
    result: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == "assistant":
            content: list[dict] = []
            if msg.content:
                content.append({"type": "text", "text": msg.content})
            for call in msg.tool_calls:
                content.append(
                    {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                )
            result.append({"role": "assistant", "content": content})
        elif msg.role == "tool":
            result.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": msg.content or "",
                        }
                    ],
                }
            )
        else:
            raise LLMProviderError(f"Unknown message role: {msg.role!r}")
    return result


class AnthropicLLMProvider(LLMProvider):
    """Real implementation, backed by the official `anthropic` SDK.
    Credentials come from `Settings.llm_api_key` — never hardcoded, never
    logged (see `docs/security.md`)."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 30.0):
        import anthropic  # imported lazily so the SDK is only required when this provider is used

        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)
        self._anthropic = anthropic
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        max_tokens: int = 1024,
    ) -> LLMResponse:
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        try:
            response = self._client.messages.create(
                model=self._model,
                system=system,
                # Built as plain dicts against the documented wire format
                # rather than the SDK's param TypedDicts, matching this
                # module's vendor-agnostic `LLMMessage`/`ToolDefinition`
                # types — the SDK accepts these at runtime.
                messages=_to_anthropic_messages(messages),  # type: ignore[arg-type]
                tools=anthropic_tools,  # type: ignore[arg-type]
                max_tokens=max_tokens,
            )
        except self._anthropic.APITimeoutError as exc:
            raise LLMProviderError(f"LLM request timed out: {exc}") from exc
        except self._anthropic.APIError as exc:
            raise LLMProviderError(f"LLM provider error: {exc}") from exc

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.id,
                        name=block.name,
                        arguments=dict(block.input) if isinstance(block.input, dict) else {},
                    )
                )

        usage = TokenUsage(
            input_tokens=response.usage.input_tokens, output_tokens=response.usage.output_tokens
        )
        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=tuple(tool_calls),
            stop_reason=response.stop_reason or "unknown",
            usage=usage,
        )


def _to_groq_messages(system: str, messages: list[LLMMessage]) -> list[dict]:
    """Groq's chat-completions API is OpenAI-compatible: a flat message
    list (system prompt as its own leading message, not a separate
    top-level param), an assistant message's requested calls under
    `tool_calls` (arguments JSON-encoded, per the wire format — not the
    dict `ToolCallRequest.arguments` holds internally), and one `"tool"`
    role message per result, matched back by `tool_call_id`."""
    result: list[dict] = [{"role": "system", "content": system}]
    for msg in messages:
        if msg.role == "user":
            result.append({"role": "user", "content": msg.content or ""})
        elif msg.role == "assistant":
            entry: dict = {"role": "assistant", "content": msg.content}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in msg.tool_calls
                ]
            result.append(entry)
        elif msg.role == "tool":
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "name": msg.tool_name,
                    "content": msg.content or "",
                }
            )
        else:
            raise LLMProviderError(f"Unknown message role: {msg.role!r}")
    return result


def _parse_groq_tool_arguments(raw: str) -> dict[str, Any]:
    """The model generates `arguments` as a JSON string it could get
    subtly wrong (truncated, not an object). Rather than let a parse
    failure crash response-parsing (a provider-level concern), this
    degrades to an empty dict — the existing per-tool Pydantic validation
    in `orchestrator.py::_execute_tool_call` already turns that into a
    clean, bounded "invalid arguments" tool error, the same path a
    genuinely malformed tool call from any provider already goes through.
    """
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class GroqLLMProvider(LLMProvider):
    """Real implementation, backed by the official `groq` SDK (OpenAI-
    compatible tool calling). Groq also offers *built-in*, server-side
    tools (web search, code execution) as an opt-in feature entirely
    separate from the `tools` parameter used here — this provider never
    requests them. AlphaLens's own 9 controlled tools (`app/agent/tools.py`)
    remain the only tool-execution surface reachable from any provider,
    Groq included (see docs/security.md)."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 30.0):
        import groq  # imported lazily so the SDK is only required when this provider is used

        self._client = groq.Groq(api_key=api_key, timeout=timeout_seconds)
        self._groq = groq
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "groq"

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        max_tokens: int = 1024,
    ) -> LLMResponse:
        groq_tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                # Plain dicts against the documented OpenAI-compatible wire
                # format, same rationale as AnthropicLLMProvider above.
                messages=_to_groq_messages(system, messages),  # type: ignore[arg-type]
                tools=groq_tools,  # type: ignore[arg-type]
                max_completion_tokens=max_tokens,
            )
        except self._groq.APITimeoutError as exc:
            raise LLMProviderError(f"LLM request timed out: {exc}") from exc
        except self._groq.APIError as exc:
            raise LLMProviderError(f"LLM provider error: {exc}") from exc

        message = response.choices[0].message
        tool_calls = tuple(
            ToolCallRequest(
                id=call.id,
                name=call.function.name,
                arguments=_parse_groq_tool_arguments(call.function.arguments),
            )
            for call in (message.tool_calls or [])
        )

        usage = None
        if response.usage is not None:
            usage = TokenUsage(
                input_tokens=response.usage.prompt_tokens,
                output_tokens=response.usage.completion_tokens,
            )

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            stop_reason=response.choices[0].finish_reason or "unknown",
            usage=usage,
        )


def _to_gemini_contents(messages: list[LLMMessage], types: Any) -> list[Any]:
    """Gemini's `contents` list has no separate "system" role — the system
    prompt is passed via `GenerateContentConfig.system_instruction`
    instead (see `GeminiLLMProvider.complete`), so this only ever
    translates user/assistant/tool turns. `types` is the already-imported
    `google.genai.types` module, passed in rather than imported here so
    this stays a plain function importable/testable without the SDK
    installed."""
    contents: list[Any] = []
    for msg in messages:
        if msg.role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=msg.content or "")]))
        elif msg.role == "assistant":
            parts = []
            if msg.content:
                parts.append(types.Part(text=msg.content))
            for call in msg.tool_calls:
                parts.append(
                    types.Part(
                        function_call=types.FunctionCall(
                            id=call.id, name=call.name, args=call.arguments
                        )
                    )
                )
            contents.append(types.Content(role="model", parts=parts))
        elif msg.role == "tool":
            # Gemini's FunctionResponse wants a dict, not the raw
            # (already prompt-injection-wrapped) string every other
            # provider passes verbatim as `content` — nesting it under
            # "result" is purely a wire-format adaptation; the actual
            # wrapped text (and its defensive reminder) is unchanged.
            #
            # role="user" here, NOT "tool" — verified against the real API
            # (Phase 8.5 live validation): a live call with role="tool"
            # fails with `400 INVALID_ARGUMENT: Role 'tool' is not
            # supported. Please use a valid role: SYSTEM, SYSTEM_1, USER,
            # ASSISTANT, DEVELOPER, CONTEXT, USER_CONTEXT, MODEL, USER.`
            # Some third-party docs describe a "tool" role for a newer
            # API surface; this project's `generate_content` + manual
            # `contents` path (the classic, non-Interactions-API surface)
            # does not accept it — see docs/decisions.md ADR-034.
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=msg.tool_call_id,
                                name=msg.tool_name or "",
                                response={"result": msg.content or ""},
                            )
                        )
                    ],
                )
            )
        else:
            raise LLMProviderError(f"Unknown message role: {msg.role!r}")
    return contents


class GeminiLLMProvider(LLMProvider):
    """Real implementation, backed by the official `google-genai` SDK's
    native function-calling. Uses classic manual function calling
    (`generate_content` plus an explicitly-built `contents` list) with
    automatic function calling disabled — the orchestrator owns the
    tool-calling loop for every provider identically, never the SDK.
    Only ever declares AlphaLens's own function tools; never enables any
    of Gemini's built-in tools (`google_search`, `code_execution`,
    `computer_use`, ...) — see docs/security.md."""

    def __init__(self, *, api_key: str, model: str, timeout_seconds: float = 30.0):
        from google import (
            genai,  # imported lazily so the SDK is only required when this provider is used
        )
        from google.genai import errors, types

        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )
        self._types = types
        self._errors = errors
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "gemini"

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        max_tokens: int = 1024,
    ) -> LLMResponse:
        types = self._types
        gemini_tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters_json_schema=t.input_schema,
                    )
                    for t in tools
                ]
            )
        ]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=gemini_tools,
            max_output_tokens=max_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=_to_gemini_contents(messages, types),
                config=config,
            )
        except self._errors.APIError as exc:
            raise LLMProviderError(f"LLM provider error: {exc}") from exc
        except Exception as exc:  # noqa: BLE001 - deliberate, narrow: the SDK
            # exposes no dedicated timeout/transport-error class (unlike
            # anthropic/groq's APITimeoutError), so this is the one place a
            # raw SDK/httpx exception is caught broadly, scoped to exactly
            # this network call, so it can never escape as an unhandled 500
            # instead of a clean AGENT_UNAVAILABLE 503.
            raise LLMProviderError(f"LLM request failed: {exc}") from exc

        candidates = response.candidates or []
        if not candidates and response.prompt_feedback and response.prompt_feedback.block_reason:
            raise LLMProviderError(
                f"LLM provider blocked the request: {response.prompt_feedback.block_reason}"
            )

        tool_calls = tuple(
            ToolCallRequest(
                id=call.id or f"gemini-call-{i}",
                name=call.name or "",
                arguments=dict(call.args) if call.args else {},
            )
            for i, call in enumerate(response.function_calls or [])
        )

        usage = None
        if response.usage_metadata is not None:
            usage = TokenUsage(
                input_tokens=response.usage_metadata.prompt_token_count or 0,
                output_tokens=response.usage_metadata.candidates_token_count or 0,
            )

        finish_reason = "unknown"
        if candidates and candidates[0].finish_reason:
            finish_reason = candidates[0].finish_reason.value

        return LLMResponse(
            content=response.text,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            usage=usage,
        )


class FakeLLMProvider(LLMProvider):
    """Deterministic test double — never calls a real API. Scripted with a
    fixed sequence of items, each either an `LLMResponse` (returned) or an
    `Exception` instance (raised) — popped in order across successive
    `.complete()` calls, so a test can simulate a provider failure/timeout
    on, say, the second call of a multi-turn exchange. Records every
    call's `(system, messages, tools)` (`self.calls`) so tests can assert
    on exactly what the orchestrator sent — e.g. that bounded conversation
    history was included, or that a news article's content was wrapped as
    untrusted data. Raises `LLMProviderError` if more calls happen than
    were scripted, rather than silently looping or fabricating a default.
    """

    def __init__(
        self, responses: list[LLMResponse | Exception], *, model: str = "fake-model-v1"
    ):
        self._responses = list(responses)
        self._model = model
        self.calls: list[dict] = []

    @property
    def model(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "fake"

    def complete(
        self,
        *,
        system: str,
        messages: list[LLMMessage],
        tools: list[ToolDefinition],
        max_tokens: int = 1024,
    ) -> LLMResponse:
        self.calls.append({"system": system, "messages": list(messages), "tools": list(tools)})
        if not self._responses:
            raise LLMProviderError("FakeLLMProvider exhausted its scripted responses")
        next_item = self._responses.pop(0)
        if isinstance(next_item, Exception):
            raise next_item
        return next_item


@lru_cache
def get_llm_provider() -> LLMProvider:
    """Registry function — the ONLY place that picks a concrete
    `LLMProvider` implementation. `LLM_PROVIDER` selects which one
    (default `"anthropic"`, so every pre-8.5 deployment's behavior is
    unchanged); each provider requires its own key, never falls back to a
    different provider than the one explicitly selected. Same registry
    pattern as `MarketDataProvider`/`NewsProvider` (ADR-002)."""
    settings = get_settings()
    provider_name = settings.llm_provider.strip().lower()

    if provider_name == "anthropic":
        if not settings.llm_api_key:
            raise LLMProviderError(
                "No LLM_API_KEY configured — the research agent cannot run without LLM "
                "credentials. Set LLM_API_KEY (and optionally LLM_MODEL) in the environment."
            )
        return AnthropicLLMProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    if provider_name == "groq":
        if not settings.groq_api_key:
            raise LLMProviderError(
                "No GROQ_API_KEY configured — set GROQ_API_KEY (and optionally GROQ_LLM_MODEL) "
                "in the environment, or set LLM_PROVIDER to a different provider."
            )
        return GroqLLMProvider(
            api_key=settings.groq_api_key,
            model=settings.groq_llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    if provider_name == "gemini":
        if not settings.gemini_api_key:
            raise LLMProviderError(
                "No GEMINI_API_KEY configured — set GEMINI_API_KEY (and optionally "
                "GEMINI_LLM_MODEL) in the environment, or set LLM_PROVIDER to a different "
                "provider."
            )
        return GeminiLLMProvider(
            api_key=settings.gemini_api_key,
            model=settings.gemini_llm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        )

    raise LLMProviderError(
        f"Unknown LLM_PROVIDER {settings.llm_provider!r} — must be one of "
        "'anthropic', 'groq', 'gemini'."
    )
