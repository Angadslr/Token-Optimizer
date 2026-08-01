"""Deterministic providers and tokenizers for isolated tests."""

from __future__ import annotations

import math
import re

from slashtoken.core.models import (
    AnswerEvaluationResult,
    ChatResult,
    ProviderTextResult,
    StageUsage,
    TokenCount,
    VerificationResult,
)


class WordTokenCounter:
    def __init__(self, *, exact: bool = True) -> None:
        self.exact = exact

    def count(self, text: str, model: str) -> TokenCount:
        return TokenCount(
            tokens=max(1, len(text.split())),
            exact=self.exact,
            tokenizer=f"test:{model}",
        )


class CharacterTokenCounter:
    def __init__(self, *, exact: bool = True) -> None:
        self.exact = exact

    def count(self, text: str, model: str) -> TokenCount:
        return TokenCount(
            tokens=max(1, len(text)), exact=self.exact, tokenizer=f"test-char:{model}"
        )


class MultilingualTokenCounter:
    """Fixture counter that models the tested target penalizing CJK input."""

    def count(self, text: str, model: str) -> TokenCount:
        cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        other = len(text) - cjk
        tokens = cjk * 2 + math.ceil(other / 4)
        return TokenCount(tokens=max(1, tokens), exact=True, tokenizer=f"fixture:{model}")


class FakeProvider:
    name = "fake"

    def __init__(self, *, candidate: str = "", verification_valid: bool = True) -> None:
        self.candidate = candidate
        self.verification_valid = verification_valid
        self.transform_calls = 0
        self.verify_calls = 0
        self.chat_calls = 0
        self.comparison_calls = 0
        self.last_chat_prompt: str | None = None

    def transform(self, **kwargs):
        self.transform_calls += 1
        candidate = self.candidate or kwargs["source_prompt"]
        return ProviderTextResult(
            text=candidate,
            usage=StageUsage(stage="prompt_transformation", model="fake", input_tokens=10, output_tokens=5),
        )

    def verify(self, **kwargs):
        self.verify_calls += 1
        return VerificationResult(
            valid=self.verification_valid,
            candidate_language="en",
            is_prompt_not_answer=True,
            preserves_requirements=self.verification_valid,
            reason="verified" if self.verification_valid else "meaning changed",
            usage=StageUsage(stage="semantic_verification", model="fake", input_tokens=10, output_tokens=2),
        )

    def chat(self, **kwargs):
        self.chat_calls += 1
        self.last_chat_prompt = kwargs["prompt"]
        return ChatResult(
            response="complete response",
            selected_route="explicit",
            usage=StageUsage(stage="target_chat", model="fake", input_tokens=4, output_tokens=3),
        )

    def compare_answers(self, **kwargs):
        self.comparison_calls += 1
        return AnswerEvaluationResult(
            acceptable=True,
            quality_score=0.95,
            preserves_constraints=True,
            reason="synthetic answers are comparable",
            usage=StageUsage(
                stage="benchmark_answer_evaluation",
                model="fake",
                input_tokens=8,
                output_tokens=2,
            ),
        )
