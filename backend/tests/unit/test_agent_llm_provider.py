import pytest
from app.agent.llm_provider import (
    FakeLLMProvider,
    LLMMessage,
    LLMProviderError,
    LLMResponse,
    ToolCallRequest,
    ToolDefinition,
)


def _final_response(text: str = "Here is the answer.") -> LLMResponse:
    return LLMResponse(content=text, tool_calls=(), stop_reason="end_turn")


class TestFakeLLMProvider:
    def test_returns_scripted_responses_in_order(self):
        first = _final_response("first")
        second = _final_response("second")
        fake = FakeLLMProvider([first, second])

        assert fake.complete(system="sys", messages=[], tools=[]) is first
        assert fake.complete(system="sys", messages=[], tools=[]) is second

    def test_raises_when_scripted_responses_are_exhausted(self):
        fake = FakeLLMProvider([_final_response()])
        fake.complete(system="sys", messages=[], tools=[])
        with pytest.raises(LLMProviderError, match="exhausted"):
            fake.complete(system="sys", messages=[], tools=[])

    def test_can_script_an_exception_to_simulate_a_provider_failure(self):
        fake = FakeLLMProvider([LLMProviderError("simulated timeout")])
        with pytest.raises(LLMProviderError, match="simulated timeout"):
            fake.complete(system="sys", messages=[], tools=[])

    def test_can_mix_responses_and_a_failure_across_calls(self):
        fake = FakeLLMProvider(
            [_final_response("ok first"), LLMProviderError("boom"), _final_response("ok third")]
        )
        assert fake.complete(system="sys", messages=[], tools=[]).content == "ok first"
        with pytest.raises(LLMProviderError, match="boom"):
            fake.complete(system="sys", messages=[], tools=[])
        assert fake.complete(system="sys", messages=[], tools=[]).content == "ok third"

    def test_records_every_call_for_test_assertions(self):
        fake = FakeLLMProvider([_final_response()])
        messages = [LLMMessage(role="user", content="hello")]
        tools = [ToolDefinition(name="t", description="d", input_schema={})]

        fake.complete(system="the-system-prompt", messages=messages, tools=tools)

        assert len(fake.calls) == 1
        assert fake.calls[0]["system"] == "the-system-prompt"
        assert fake.calls[0]["messages"] == messages
        assert fake.calls[0]["tools"] == tools

    def test_model_and_provider_name_are_reported(self):
        fake = FakeLLMProvider([_final_response()], model="fake-test-model")
        assert fake.model == "fake-test-model"
        assert fake.provider_name == "fake"

    def test_tool_call_request_is_preserved_on_the_response(self):
        call = ToolCallRequest(id="call_1", name="get_forecast", arguments={"ticker": "AAPL"})
        response = LLMResponse(content=None, tool_calls=(call,), stop_reason="tool_use")
        fake = FakeLLMProvider([response])

        result = fake.complete(system="sys", messages=[], tools=[])

        assert result.tool_calls == (call,)
