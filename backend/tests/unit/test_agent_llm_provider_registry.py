"""Tests for `get_llm_provider()` — the one place that picks a concrete
`LLMProvider` (Phase 8.5 added Groq/Gemini alongside Anthropic). Mutates
the cached `Settings` singleton directly (same pattern
`test_forecast.py::test_forecast_returns_503_when_model_registry_is_missing`
uses) so `monkeypatch` cleans it up automatically; `get_llm_provider`
itself is also `@lru_cache`d, so its cache is explicitly cleared before
and after every test in this file to avoid leaking a stale provider
instance into unrelated tests elsewhere in the suite.
"""

from __future__ import annotations

import pytest
from app.agent.llm_provider import (
    AnthropicLLMProvider,
    GeminiLLMProvider,
    GroqLLMProvider,
    LLMProviderError,
    get_llm_provider,
)
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _reset_llm_provider_cache():
    get_llm_provider.cache_clear()
    yield
    get_llm_provider.cache_clear()


class TestDefaultProvider:
    def test_default_llm_provider_is_anthropic(self):
        settings = get_settings()
        assert settings.llm_provider == "anthropic"

    def test_missing_anthropic_key_raises_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_api_key", "")

        with pytest.raises(LLMProviderError, match="LLM_API_KEY"):
            get_llm_provider()

    def test_anthropic_key_present_returns_an_anthropic_provider(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_api_key", "fake-anthropic-key")
        monkeypatch.setattr(get_settings(), "llm_model", "claude-haiku-4-5-20251001")

        provider = get_llm_provider()

        assert isinstance(provider, AnthropicLLMProvider)
        assert provider.model == "claude-haiku-4-5-20251001"


class TestGroqSelection:
    def test_missing_groq_key_raises_an_error_naming_groq_api_key(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_provider", "groq")
        monkeypatch.setattr(get_settings(), "groq_api_key", "")

        with pytest.raises(LLMProviderError, match="GROQ_API_KEY"):
            get_llm_provider()

    def test_groq_key_present_returns_a_groq_provider_with_the_configured_model(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_provider", "groq")
        monkeypatch.setattr(get_settings(), "groq_api_key", "fake-groq-key")
        monkeypatch.setattr(get_settings(), "groq_llm_model", "openai/gpt-oss-120b")

        provider = get_llm_provider()

        assert isinstance(provider, GroqLLMProvider)
        assert provider.model == "openai/gpt-oss-120b"

    def test_selecting_groq_never_falls_back_to_anthropic(self, monkeypatch):
        """Even if an Anthropic key happens to also be set, requesting Groq
        must never silently use a different provider than the one asked
        for."""
        monkeypatch.setattr(get_settings(), "llm_provider", "groq")
        monkeypatch.setattr(get_settings(), "groq_api_key", "")
        monkeypatch.setattr(get_settings(), "llm_api_key", "fake-anthropic-key")

        with pytest.raises(LLMProviderError, match="GROQ_API_KEY"):
            get_llm_provider()


class TestGeminiSelection:
    def test_missing_gemini_key_raises_an_error_naming_gemini_api_key(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_provider", "gemini")
        monkeypatch.setattr(get_settings(), "gemini_api_key", "")

        with pytest.raises(LLMProviderError, match="GEMINI_API_KEY"):
            get_llm_provider()

    def test_gemini_key_present_returns_a_gemini_provider_with_the_configured_model(
        self, monkeypatch
    ):
        monkeypatch.setattr(get_settings(), "llm_provider", "gemini")
        monkeypatch.setattr(get_settings(), "gemini_api_key", "fake-gemini-key")
        monkeypatch.setattr(get_settings(), "gemini_llm_model", "gemini-3-flash")

        provider = get_llm_provider()

        assert isinstance(provider, GeminiLLMProvider)
        assert provider.model == "gemini-3-flash"


class TestUnknownProvider:
    def test_an_unrecognized_provider_name_raises_a_clear_error(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_provider", "some-future-vendor")

        with pytest.raises(LLMProviderError, match="some-future-vendor"):
            get_llm_provider()

    def test_provider_name_matching_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "llm_provider", "GROQ")
        monkeypatch.setattr(get_settings(), "groq_api_key", "fake-groq-key")

        provider = get_llm_provider()

        assert isinstance(provider, GroqLLMProvider)
