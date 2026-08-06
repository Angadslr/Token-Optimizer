"""Replaceable provider, tokenizer, and pricing contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from slashtoken.core.models import (
    AnswerEvaluationResult,
    CandidateLanguageAssessment,
    ChatResult,
    ProtectedSpan,
    ProviderTextResult,
    TokenCount,
    VerificationResult,
    WorkloadMode,
)


class ProviderError(RuntimeError):
    """Base class for safe, provider-independent hosted service failures."""


class ProviderUnavailableError(ProviderError):
    """Raised after retryable hosted-provider failures exhaust automatic retries."""

    def __init__(self, *, stage: str, status_code: int | None = None) -> None:
        self.stage = stage
        self.status_code = status_code
        status = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(
            "Hosted provider temporarily unavailable during "
            f"{stage} after automatic retries{status}."
        )

    @property
    def safe_cause(self) -> str:
        """Privacy-safe failure class for receipts; never upstream response text."""
        if self.status_code is not None:
            return f"HTTP {self.status_code}"
        return "timeout_or_connection"


class OptimizationProvider(Protocol):
    name: str

    def transform(
        self,
        *,
        source_prompt: str,
        source_language: str,
        response_language: str,
        protected_spans: tuple[ProtectedSpan, ...],
    ) -> ProviderTextResult: ...

    def verify(
        self,
        *,
        source_prompt: str,
        candidate_prompt: str,
        source_language: str,
        response_language: str,
    ) -> VerificationResult: ...

    def chat(
        self,
        *,
        prompt: str,
        response_language: str,
        workload_mode: WorkloadMode,
        output_optimization: bool = False,
    ) -> ChatResult: ...

    def compare_answers(
        self,
        *,
        source_prompt: str,
        baseline_answer: str,
        optimized_answer: str,
        source_language: str,
    ) -> AnswerEvaluationResult: ...


class TokenCounter(Protocol):
    def count(self, text: str, model: str) -> TokenCount: ...


class CandidateLanguageDetector(Protocol):
    def assess_english(self, text: str) -> CandidateLanguageAssessment: ...


@dataclass(frozen=True, slots=True)
class ModelPrice:
    input_per_million_usd: float
    output_per_million_usd: float
    cached_input_per_million_usd: float = 0.0


class PricingCatalog:
    """Versioned model pricing used for end-to-end API calculations."""

    def __init__(self, prices: dict[str, ModelPrice] | None = None) -> None:
        self._prices = dict(prices or {})

    def estimate(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        cached_input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> float:
        price = self._prices.get(model)
        if price is None:
            return 0.0
        return (
            input_tokens * price.input_per_million_usd
            + cached_input_tokens * price.cached_input_per_million_usd
            + output_tokens * price.output_per_million_usd
        ) / 1_000_000

    def has_price(self, model: str) -> bool:
        return model in self._prices


class ApproximateTokenCounter:
    """Dependency-free preview estimate; never marked exact for auto-routing."""

    def count(self, text: str, model: str) -> TokenCount:
        utf8_bytes = len(text.encode("utf-8"))
        ascii_chars = sum(character.isascii() for character in text)
        non_ascii_chars = len(text) - ascii_chars
        estimate = math.ceil(ascii_chars / 4 + non_ascii_chars / 1.6)
        return TokenCount(
            tokens=max(1, estimate),
            exact=False,
            tokenizer=f"approximate-utf8:{model}",
        )


# Families that share OpenAI's o200k_base encoding (GPT-5.x website tokenizer).
# tiktoken's built-in map covers `gpt-5` / `gpt-5-*` but not dotted IDs like
# `gpt-5.6` or Codex suffixes like `gpt-5.6-terra`.
_O200K_MODEL_PREFIXES = (
    "gpt-5",
    "gpt-4.1",
    "gpt-4.5",
    "gpt-4o",
    "chatgpt-4o",
    "o1",
    "o3",
    "o4-mini",
)


def model_uses_o200k_base(model: str) -> bool:
    """Return True when *model* should use the o200k_base tokenizer."""
    normalized = model.strip().lower()
    if normalized.startswith("ft:"):
        normalized = normalized[3:]
    return any(
        normalized == prefix
        or normalized.startswith(f"{prefix}-")
        or normalized.startswith(f"{prefix}.")
        for prefix in _O200K_MODEL_PREFIXES
    )


class TiktokenCounter:
    """Target-model counter with an explicit approximate fallback."""

    def __init__(self) -> None:
        self._fallback = ApproximateTokenCounter()

    def count(self, text: str, model: str) -> TokenCount:
        try:
            import tiktoken
        except ImportError:
            return self._fallback.count(text, model)

        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            if not model_uses_o200k_base(model):
                return self._fallback.count(text, model)
            encoding = tiktoken.get_encoding("o200k_base")

        return TokenCount(
            tokens=len(encoding.encode(text)),
            exact=True,
            tokenizer=f"tiktoken:{encoding.name}",
        )
