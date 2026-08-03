"""Immutable domain models shared by every SlashToken adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any
from uuid import uuid4


class WorkloadMode(StrEnum):
    CHATBOT = "chatbot"
    AGENTIC_CODING = "agentic_coding"


class ApprovalPolicy(StrEnum):
    PREVIEW_EACH = "preview_each"
    AUTO_VERIFIED = "auto_verified"


class ResponseLanguage(StrEnum):
    PRESERVE_SOURCE = "preserve_source"
    ENGLISH = "english"


class DecisionStatus(StrEnum):
    CANDIDATE = "candidate"
    BYPASSED = "bypassed"
    REJECTED = "rejected"
    FAILED = "failed"


class FallbackReason(StrEnum):
    LANGUAGE_OPTIMIZATION_DISABLED = "language_optimization_disabled"
    ALREADY_ENGLISH = "already_english"
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    HIGH_STAKES = "high_stakes"
    BELOW_BREAK_EVEN = "below_break_even"
    NO_TOKEN_SAVINGS = "no_token_savings"
    INEXACT_TOKENIZER = "inexact_tokenizer"
    PROTECTED_SPAN_MISMATCH = "protected_span_mismatch"
    VERIFICATION_FAILED = "verification_failed"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class ProtectedSpan:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class TokenCount:
    tokens: int
    exact: bool
    tokenizer: str


@dataclass(frozen=True, slots=True)
class StageUsage:
    stage: str
    model: str
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float = 0.0
    pricing_available: bool = False
    latency_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class ProviderTextResult:
    text: str
    usage: StageUsage


@dataclass(frozen=True, slots=True)
class VerificationResult:
    valid: bool
    candidate_language: str
    is_prompt_not_answer: bool
    preserves_requirements: bool
    reason: str
    usage: StageUsage


@dataclass(frozen=True, slots=True)
class AnswerEvaluationResult:
    acceptable: bool
    quality_score: float
    preserves_constraints: bool
    reason: str
    usage: StageUsage


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    prompt: str
    target_model: str
    response_language: ResponseLanguage = ResponseLanguage.PRESERVE_SOURCE
    project_path: str | None = None
    workload_mode: WorkloadMode = WorkloadMode.AGENTIC_CODING

    def normalized_prompt(self) -> str:
        normalized = self.prompt.strip()
        if not normalized:
            raise ValueError("Prompt cannot be empty.")
        return normalized


@dataclass(frozen=True, slots=True)
class PromptAnalysis:
    source_language: str
    supported: bool
    high_stakes: bool
    risk_categories: tuple[str, ...]
    protected_spans: tuple[ProtectedSpan, ...]
    original_tokens: TokenCount


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    status: DecisionStatus
    source_language: str
    original_tokens: TokenCount
    candidate_tokens: TokenCount | None
    candidate_prompt: str | None
    fallback_reason: FallbackReason | None
    receipt: str
    verification: VerificationResult | None = None
    stage_usage: tuple[StageUsage, ...] = field(default_factory=tuple)
    protected_span_count: int = 0
    auto_run_eligible: bool = False
    threshold_version: str = "uncalibrated-v1"
    decision_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def token_savings(self) -> int:
        if self.candidate_tokens is None:
            return 0
        return self.original_tokens.tokens - self.candidate_tokens.tokens

    @property
    def token_savings_percent(self) -> float:
        if self.original_tokens.tokens <= 0:
            return 0.0
        return self.token_savings / self.original_tokens.tokens * 100

    @property
    def optimizer_cost_usd(self) -> float:
        return sum(item.estimated_cost_usd for item in self.stage_usage)

    @property
    def optimizer_cost_available(self) -> bool:
        return bool(self.stage_usage) and all(
            item.pricing_available for item in self.stage_usage
        )

    def public_dict(self, *, include_candidate: bool = True) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["fallback_reason"] = (
            self.fallback_reason.value if self.fallback_reason else None
        )
        payload["token_savings"] = self.token_savings
        payload["token_savings_percent"] = round(self.token_savings_percent, 2)
        payload["optimizer_cost_usd"] = round(self.optimizer_cost_usd, 10)
        payload["optimizer_cost_available"] = self.optimizer_cost_available
        if not include_candidate:
            payload.pop("candidate_prompt", None)
        return payload


@dataclass(frozen=True, slots=True)
class ChatResult:
    response: str
    selected_route: str
    usage: StageUsage
    decision_id: str | None = None
