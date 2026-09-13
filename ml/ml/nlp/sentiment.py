"""Financial sentiment via FinBERT (`ProsusAI/finbert`). Standalone `ml/`
code — no FastAPI import; `backend/app/services/news_sentiment_service.py`
is the only thing that calls into this module (ADR-001), and it never
trains anything — it only loads an already-fine-tuned checkpoint from the
Hugging Face Hub and runs inference.

**Sentiment is an informational signal, not a guaranteed trading signal.**
FinBERT's output describes the emotional/informational tone of a piece of
text — it is not a claim that this tone predicts the subject security's
future return. No code in this module, and no code anywhere in this phase,
computes or implies a return forecast from sentiment; see
docs/ml-pipeline.md "Financial sentiment" for the full methodology note
and the explicit absence of any such backtest in this phase.

The model is loaded once per process (`get_sentiment_analyzer()`'s
module-level cache), never repeatedly per article — `analyze_batch` is the
preferred entry point for more than one text (one batched forward pass,
not N individual ones); see docs/ml-pipeline.md "Performance" for how the
news-ingestion service uses this.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL_NAME = "ProsusAI/finbert"
# Pinned to an exact commit, not "whatever `main` currently points to" —
# every deployment/run uses identical weights, and this value is what gets
# recorded as `model_version` on every stored `NewsSentiment` row.
MODEL_REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"
MAX_SEQUENCE_LENGTH = 512


@dataclass(frozen=True)
class SentimentResult:
    positive: float
    neutral: float
    negative: float
    predicted_label: str
    model_name: str
    model_version: str

    def as_dict(self) -> dict:
        return {
            "positive": self.positive,
            "neutral": self.neutral,
            "negative": self.negative,
            "predicted_label": self.predicted_label,
            "model_name": self.model_name,
            "model_version": self.model_version,
        }


class FinBertSentimentAnalyzer:
    """Loads the FinBERT tokenizer+model once in `__init__` — construct one
    instance per process (see `get_sentiment_analyzer()`), never per
    article."""

    def __init__(self, model_name: str = MODEL_NAME, revision: str = MODEL_REVISION):
        self.model_name = model_name
        self.model_version = revision
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, revision=revision)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            model_name, revision=revision
        )
        self._model.eval()
        # id2label order is NOT guaranteed alphabetical — FinBERT's own
        # checkpoint is `{0: "positive", 1: "negative", 2: "neutral"}` —
        # always read it from the model's own config, never hardcode an
        # index order.
        self._id2label = {i: label.lower() for i, label in self._model.config.id2label.items()}

    def analyze_batch(self, texts: list[str]) -> list[SentimentResult]:
        """One batched forward pass for the whole list — never one FinBERT
        call per text. Raises `TypeError`/`ValueError` on a non-string or
        empty/whitespace-only entry rather than silently padding it into a
        fabricated result; text longer than `MAX_SEQUENCE_LENGTH` tokens is
        truncated by the tokenizer (FinBERT's own input limit), not an
        error."""
        if not texts:
            return []
        for text in texts:
            if not isinstance(text, str):
                raise TypeError(f"analyze_batch() expects strings, got {type(text).__name__}")
            if not text.strip():
                raise ValueError("analyze_batch() received an empty/whitespace-only text")

        inputs = self._tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=MAX_SEQUENCE_LENGTH,
        )
        with torch.no_grad():
            logits = self._model(**inputs).logits
        probabilities = torch.nn.functional.softmax(logits, dim=-1)

        results = []
        for row in probabilities:
            by_label = {self._id2label[i]: float(p) for i, p in enumerate(row)}
            predicted_index = int(torch.argmax(row))
            results.append(
                SentimentResult(
                    positive=by_label["positive"],
                    neutral=by_label["neutral"],
                    negative=by_label["negative"],
                    predicted_label=self._id2label[predicted_index],
                    model_name=self.model_name,
                    model_version=self.model_version,
                )
            )
        return results

    def analyze_sentiment(self, text: str) -> SentimentResult:
        return self.analyze_batch([text])[0]


@lru_cache(maxsize=1)
def get_sentiment_analyzer() -> FinBertSentimentAnalyzer:
    """Process-wide singleton — the model is loaded from disk/the Hugging
    Face cache exactly once per process, regardless of how many articles
    are analyzed over that process's lifetime."""
    return FinBertSentimentAnalyzer()


def analyze_sentiment(text: str) -> SentimentResult:
    """Convenience wrapper around the process-wide singleton analyzer."""
    return get_sentiment_analyzer().analyze_sentiment(text)


def analyze_batch(texts: list[str]) -> list[SentimentResult]:
    """Convenience wrapper around the process-wide singleton analyzer —
    prefer this over calling `analyze_sentiment` in a loop."""
    return get_sentiment_analyzer().analyze_batch(texts)
