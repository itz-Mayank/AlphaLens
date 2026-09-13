"""Tests for `ml.nlp.sentiment` — real FinBERT inference (the model is
downloaded once to the local Hugging Face cache; these tests do not mock
the model). Marked as needing network on first run only; once cached,
loading is local-disk-only and fast."""

from __future__ import annotations

import pytest
from ml.nlp.sentiment import (
    MODEL_NAME,
    MODEL_REVISION,
    analyze_batch,
    analyze_sentiment,
    get_sentiment_analyzer,
)


@pytest.fixture(scope="module")
def analyzer():
    return get_sentiment_analyzer()


class TestAnalyzeSentiment:
    def test_returns_valid_probability_distribution(self, analyzer):
        result = analyzer.analyze_sentiment("Company reports strong quarterly earnings.")
        total = result.positive + result.neutral + result.negative
        assert total == pytest.approx(1.0, abs=1e-4)
        assert 0.0 <= result.positive <= 1.0
        assert 0.0 <= result.neutral <= 1.0
        assert 0.0 <= result.negative <= 1.0

    def test_predicted_label_is_one_of_the_three_classes(self, analyzer):
        result = analyzer.analyze_sentiment("The company announced a new product.")
        assert result.predicted_label in {"positive", "neutral", "negative"}

    def test_predicted_label_matches_the_highest_probability(self, analyzer):
        result = analyzer.analyze_sentiment("Shares plunge after fraud investigation announced.")
        probs = {
            "positive": result.positive,
            "neutral": result.neutral,
            "negative": result.negative,
        }
        assert result.predicted_label == max(probs, key=probs.get)

    def test_records_model_name_and_version(self, analyzer):
        result = analyzer.analyze_sentiment("Neutral announcement about a scheduled meeting.")
        assert result.model_name == MODEL_NAME
        assert result.model_version == MODEL_REVISION

    def test_clearly_positive_text_is_predicted_positive(self, analyzer):
        result = analyzer.analyze_sentiment(
            "The company reported record profits, beating analyst expectations by a wide margin."
        )
        assert result.predicted_label == "positive"

    def test_clearly_negative_text_is_predicted_negative(self, analyzer):
        result = analyzer.analyze_sentiment(
            "The company's shares collapsed after a massive accounting fraud was uncovered."
        )
        assert result.predicted_label == "negative"

    def test_deterministic_across_repeated_calls(self, analyzer):
        text = "The company will hold its annual shareholder meeting next month."
        first = analyzer.analyze_sentiment(text)
        second = analyzer.analyze_sentiment(text)
        assert first == second

    def test_empty_string_raises(self, analyzer):
        with pytest.raises(ValueError, match="empty"):
            analyzer.analyze_sentiment("")

    def test_whitespace_only_raises(self, analyzer):
        with pytest.raises(ValueError, match="empty"):
            analyzer.analyze_sentiment("   \n\t  ")

    def test_non_string_input_raises_type_error(self, analyzer):
        with pytest.raises(TypeError):
            analyzer.analyze_sentiment(12345)  # type: ignore[arg-type]

    def test_very_long_input_is_truncated_not_an_error(self, analyzer):
        long_text = "The company reported strong earnings growth. " * 300  # far over 512 tokens
        result = analyzer.analyze_sentiment(long_text)
        assert result.predicted_label in {"positive", "neutral", "negative"}


class TestAnalyzeBatch:
    def test_empty_list_returns_empty_list(self, analyzer):
        assert analyzer.analyze_batch([]) == []

    def test_batch_matches_individual_calls(self, analyzer):
        """Batched and one-at-a-time inference must agree on the predicted
        label and probabilities to within floating-point tolerance — exact
        bit-for-bit equality isn't guaranteed because batching pads shorter
        sequences to the batch's longest one, and attention over a padded
        vs. unpadded sequence can differ at the ~1e-6 level (a well-known,
        benign floating-point effect of batching, not a bug)."""
        texts = [
            "Company reports record profits.",
            "Company shares plunge after scandal.",
            "Company schedules its annual meeting.",
        ]
        batch_results = analyzer.analyze_batch(texts)
        individual_results = [analyzer.analyze_sentiment(t) for t in texts]
        for batched, individual in zip(batch_results, individual_results, strict=True):
            assert batched.predicted_label == individual.predicted_label
            assert batched.positive == pytest.approx(individual.positive, abs=1e-4)
            assert batched.neutral == pytest.approx(individual.neutral, abs=1e-4)
            assert batched.negative == pytest.approx(individual.negative, abs=1e-4)

    def test_one_empty_text_in_a_batch_raises(self, analyzer):
        with pytest.raises(ValueError, match="empty"):
            analyzer.analyze_batch(["Good news for the company.", ""])

    def test_module_level_convenience_functions_use_the_shared_singleton(self):
        assert (
            analyze_sentiment("A neutral company statement was released.").model_name == MODEL_NAME
        )
        assert len(analyze_batch(["First article text.", "Second article text."])) == 2


class TestGetSentimentAnalyzer:
    def test_returns_the_same_instance_every_call(self):
        assert get_sentiment_analyzer() is get_sentiment_analyzer()
