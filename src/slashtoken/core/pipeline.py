"""End-to-end prompt analysis and verified optimization orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from slashtoken.core.models import (
    CandidateLanguageAssessment,
    DecisionStatus,
    FallbackReason,
    OptimizationRequest,
    PromptAnalysis,
    ProtectedSpan,
    ResponseLanguage,
    RoutingDecision,
    VerificationResult,
)
from slashtoken.core.protection import (
    ProtectedPlaceholderError,
    extract_protected_spans,
    missing_protected_spans,
    prioritize_protected_spans,
    restore_protected_spans,
    shield_protected_spans,
    summarize_placeholder_failure,
    validate_protected_placeholders,
    without_protected_values,
)
from slashtoken.core.risk import (
    SUPPORTED_LANGUAGES,
    ConservativeCandidateLanguageDetector,
    classify_risk,
    detect_language,
)
from slashtoken.core.routing import ThresholdRegistry
from slashtoken.providers.base import (
    CandidateLanguageDetector,
    OptimizationProvider,
    ProviderUnavailableError,
    TokenCounter,
)


_LANGUAGE_NAMES = {
    "zh": "the same Chinese variety used by the source prompt",
    "ar": "Arabic",
    "tr": "Turkish",
    "en": "English",
    "und": "the source language",
}


def response_language_name(source_language: str) -> str:
    """Return a concrete provider instruction for a detected source language."""
    return _LANGUAGE_NAMES.get(source_language, "the source language")


class DecisionRecorder(Protocol):
    def record_decision(self, request: OptimizationRequest, decision: RoutingDecision) -> None: ...


class OptimizationPipeline:
    """Coordinates safe routing without binding callers to any UI or protocol."""

    def __init__(
        self,
        *,
        provider: OptimizationProvider,
        token_counter: TokenCounter,
        thresholds: ThresholdRegistry | None = None,
        recorder: DecisionRecorder | None = None,
        minimum_source_tokens: int = 12,
        candidate_language_detector: CandidateLanguageDetector | None = None,
        protected_span_soft_limit: int = 40,
        transform_retry_attempts: int = 2,
    ) -> None:
        self.provider = provider
        self.token_counter = token_counter
        self.thresholds = thresholds or ThresholdRegistry()
        self.recorder = recorder
        self.minimum_source_tokens = minimum_source_tokens
        self.candidate_language_detector = (
            candidate_language_detector or ConservativeCandidateLanguageDetector()
        )
        self.protected_span_soft_limit = protected_span_soft_limit
        self.transform_retry_attempts = max(1, transform_retry_attempts)

    def analyze(self, request: OptimizationRequest) -> PromptAnalysis:
        prompt = request.normalized_prompt()
        language = detect_language(prompt)
        risk = classify_risk(prompt)
        spans = prioritize_protected_spans(
            extract_protected_spans(prompt), soft_limit=self.protected_span_soft_limit
        )
        original_tokens = self.token_counter.count(prompt, request.target_model)
        return PromptAnalysis(
            source_language=language,
            supported=language in SUPPORTED_LANGUAGES,
            high_stakes=risk.high_stakes,
            risk_categories=risk.categories,
            protected_spans=spans,
            original_tokens=original_tokens,
        )

    def optimize(
        self, request: OptimizationRequest, *, language_optimization: bool = True
    ) -> RoutingDecision:
        prompt = request.normalized_prompt()
        analysis = self.analyze(request)

        if not language_optimization:
            return self._finish(
                request,
                self._bypass(
                    analysis,
                    FallbackReason.LANGUAGE_OPTIMIZATION_DISABLED,
                    "Language optimization is disabled. The original prompt is ready for approval.",
                ),
            )
        if analysis.source_language == "en":
            return self._finish(
                request,
                self._bypass(
                    analysis,
                    FallbackReason.ALREADY_ENGLISH,
                    "The prompt is already English, so multilingual transformation was bypassed.",
                ),
            )
        if not analysis.supported:
            return self._finish(
                request,
                self._bypass(
                    analysis,
                    FallbackReason.UNSUPPORTED_LANGUAGE,
                    "This language is not benchmark-supported in SlashToken v1.",
                ),
            )
        if analysis.high_stakes:
            categories = ", ".join(analysis.risk_categories)
            return self._finish(
                request,
                self._bypass(
                    analysis,
                    FallbackReason.HIGH_STAKES,
                    f"Language transformation was bypassed because the prompt appears high-stakes ({categories}).",
                ),
            )
        if analysis.original_tokens.tokens < self.minimum_source_tokens:
            return self._finish(
                request,
                self._bypass(
                    analysis,
                    FallbackReason.BELOW_BREAK_EVEN,
                    "The prompt is too short for hosted transformation overhead to be worthwhile.",
                ),
            )

        response_language = self._response_language(
            request.response_language, analysis.source_language
        )
        completed_usage = ()
        candidate_language = None
        try:
            shielded = shield_protected_spans(prompt, analysis.protected_spans)
            threshold = self.thresholds.get(
                analysis.source_language, request.target_model
            )
            transform_usages: list = []
            transformed = None
            placeholder_error = True
            for _ in range(self.transform_retry_attempts):
                transformed = self.provider.transform(
                    source_prompt=shielded.text,
                    source_language=analysis.source_language,
                    response_language=response_language,
                    protected_spans=shielded.placeholder_spans,
                )
                transform_usages.append(transformed.usage)
                completed_usage = tuple(transform_usages)
                try:
                    validate_protected_placeholders(transformed.text, shielded)
                    placeholder_error = False
                    break
                except ProtectedPlaceholderError:
                    placeholder_error = True

            transform_stage_usage = tuple(transform_usages)
            if placeholder_error:
                diagnostics = summarize_placeholder_failure(transformed.text, shielded)
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=None,
                        candidate_prompt=None,
                        fallback_reason=FallbackReason.PROTECTED_SPAN_MISMATCH,
                        receipt=(
                            "Candidate rejected because a protected placeholder was "
                            "changed, duplicated, reordered, or removed "
                            f"({diagnostics})."
                        ),
                        stage_usage=transform_stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            candidate_language = self._assess_candidate_language(
                transformed.text, shielded.placeholder_spans
            )
            if not candidate_language.reliable:
                detected = candidate_language.detected_language or "undetermined"
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=None,
                        candidate_prompt=None,
                        fallback_reason=FallbackReason.WRONG_CANDIDATE_LANGUAGE,
                        receipt=(
                            "Candidate rejected because the compact-English route "
                            f"detected {detected!r} instead of reliable English. "
                            "Use the original prompt."
                        ),
                        candidate_language=candidate_language,
                        stage_usage=transform_stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            candidate_prompt = restore_protected_spans(transformed.text, shielded)
            missing = missing_protected_spans(candidate_prompt, analysis.protected_spans)
            if missing:
                kinds = ", ".join(sorted({span.kind for span in missing}))
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=None,
                        candidate_prompt=None,
                        fallback_reason=FallbackReason.PROTECTED_SPAN_MISMATCH,
                        receipt=(
                            "Candidate rejected because protected "
                            f"{kinds} content changed or disappeared."
                        ),
                        candidate_language=candidate_language,
                        stage_usage=transform_stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            candidate_tokens = self.token_counter.count(
                candidate_prompt, request.target_model
            )

            if candidate_tokens.tokens >= analysis.original_tokens.tokens:
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=candidate_prompt,
                        fallback_reason=FallbackReason.NO_TOKEN_SAVINGS,
                        receipt=(
                            "The candidate did not reduce target-model input tokens; "
                            "use the original prompt."
                        ),
                        candidate_language=candidate_language,
                        stage_usage=transform_stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            qualifies = threshold.qualifies(
                analysis.original_tokens.tokens, candidate_tokens.tokens
            )
            if not qualifies:
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=candidate_prompt,
                        fallback_reason=FallbackReason.BELOW_BREAK_EVEN,
                        receipt=(
                            "The candidate reduced tokens but did not meet the configured "
                            "minimum-savings threshold; use the original prompt."
                        ),
                        candidate_language=candidate_language,
                        stage_usage=transform_stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            verification = self.provider.verify(
                source_prompt=prompt,
                candidate_prompt=candidate_prompt,
                source_language=analysis.source_language,
                response_language=response_language,
            )
            stage_usage = (*transform_stage_usage, verification.usage)
            if not verification.valid:
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=candidate_prompt,
                        fallback_reason=FallbackReason.VERIFICATION_FAILED,
                        receipt=f"Semantic verification rejected the candidate: {verification.reason}",
                        verification=verification,
                        candidate_language=candidate_language,
                        stage_usage=stage_usage,
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            auto_eligible = bool(
                threshold.calibrated
                and qualifies
                and analysis.original_tokens.exact
                and candidate_tokens.exact
            )
            auto_note = (
                "It meets the calibrated auto-run threshold."
                if auto_eligible
                else "It requires approval because this language/model threshold is not calibrated or token counts are approximate."
            )
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.CANDIDATE,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=candidate_tokens,
                    candidate_prompt=candidate_prompt,
                    fallback_reason=(
                        None
                        if analysis.original_tokens.exact and candidate_tokens.exact
                        else FallbackReason.INEXACT_TOKENIZER
                    ),
                    receipt=(
                        f"Verified candidate saves {analysis.original_tokens.tokens - candidate_tokens.tokens} "
                        f"estimated input tokens. {auto_note}"
                    ),
                    verification=verification,
                    candidate_language=candidate_language,
                    stage_usage=stage_usage,
                    protected_span_count=len(analysis.protected_spans),
                    auto_run_eligible=auto_eligible,
                    threshold_version=threshold.version,
                ),
            )
        except ProviderUnavailableError as error:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.BYPASSED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=None,
                    candidate_prompt=None,
                    fallback_reason=FallbackReason.PROVIDER_UNAVAILABLE,
                    receipt=(
                        "Hosted language optimization is temporarily unavailable after "
                        f"automatic retries (stage: {error.stage}, cause: {error.safe_cause}). "
                        "The original-language prompt is ready for approval; no prompt was "
                        "submitted. Output optimization will still apply if it is enabled "
                        "when you submit the original."
                    ),
                    candidate_language=candidate_language,
                    stage_usage=tuple(completed_usage),
                    protected_span_count=len(analysis.protected_spans),
                ),
            )
        except Exception as error:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.FAILED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=None,
                    candidate_prompt=None,
                    fallback_reason=FallbackReason.PROVIDER_ERROR,
                    receipt=(
                        "Hosted optimization failed; no prompt was submitted. "
                        f"Failure category: {type(error).__name__}."
                    ),
                    protected_span_count=len(analysis.protected_spans),
                ),
            )

    def reverify_candidate(
        self,
        request: OptimizationRequest,
        candidate_prompt: str,
    ) -> RoutingDecision:
        """Re-run all post-transformation gates after a user edits a candidate."""
        prompt = request.normalized_prompt()
        candidate = candidate_prompt.strip()
        if not candidate:
            raise ValueError("Edited candidate cannot be empty.")
        analysis = self.analyze(request)
        threshold = self.thresholds.get(analysis.source_language, request.target_model)
        missing = missing_protected_spans(candidate, analysis.protected_spans)
        if missing:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=None,
                    candidate_prompt=None,
                    fallback_reason=FallbackReason.PROTECTED_SPAN_MISMATCH,
                    receipt="Edited candidate changed or removed protected content.",
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        candidate_language = self._assess_candidate_language(
            candidate, analysis.protected_spans
        )
        if not candidate_language.reliable:
            detected = candidate_language.detected_language or "undetermined"
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=None,
                    candidate_prompt=None,
                    fallback_reason=FallbackReason.WRONG_CANDIDATE_LANGUAGE,
                    receipt=(
                        "Edited candidate rejected because the compact-English route "
                        f"detected {detected!r} instead of reliable English."
                    ),
                    candidate_language=candidate_language,
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        candidate_tokens = self.token_counter.count(candidate, request.target_model)
        if candidate_tokens.tokens >= analysis.original_tokens.tokens:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=candidate_tokens,
                    candidate_prompt=candidate,
                    fallback_reason=FallbackReason.NO_TOKEN_SAVINGS,
                    receipt="Edited candidate no longer reduces target-model input tokens.",
                    candidate_language=candidate_language,
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        qualifies = threshold.qualifies(
            analysis.original_tokens.tokens, candidate_tokens.tokens
        )
        if not qualifies:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=candidate_tokens,
                    candidate_prompt=candidate,
                    fallback_reason=FallbackReason.BELOW_BREAK_EVEN,
                    receipt=(
                        "Edited candidate does not meet the configured minimum-savings "
                        "threshold."
                    ),
                    candidate_language=candidate_language,
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        response_language = self._response_language(
            request.response_language, analysis.source_language
        )
        verification = self.provider.verify(
            source_prompt=prompt,
            candidate_prompt=candidate,
            source_language=analysis.source_language,
            response_language=response_language,
        )
        if not verification.valid:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=candidate_tokens,
                    candidate_prompt=candidate,
                    fallback_reason=FallbackReason.VERIFICATION_FAILED,
                    receipt=f"Edited candidate failed semantic verification: {verification.reason}",
                    verification=verification,
                    candidate_language=candidate_language,
                    stage_usage=(verification.usage,),
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        return self._finish(
            request,
            RoutingDecision(
                status=DecisionStatus.CANDIDATE,
                source_language=analysis.source_language,
                original_tokens=analysis.original_tokens,
                candidate_tokens=candidate_tokens,
                candidate_prompt=candidate,
                fallback_reason=None,
                receipt="Edited candidate passed deterministic and semantic verification.",
                verification=verification,
                candidate_language=candidate_language,
                stage_usage=(verification.usage,),
                protected_span_count=len(analysis.protected_spans),
                auto_run_eligible=bool(
                    threshold.calibrated
                    and qualifies
                    and analysis.original_tokens.exact
                    and candidate_tokens.exact
                ),
                threshold_version=threshold.version,
            ),
        )

    def _assess_candidate_language(
        self, candidate: str, protected_spans: Iterable[ProtectedSpan]
    ) -> CandidateLanguageAssessment:
        sample = without_protected_values(candidate, protected_spans)
        return self.candidate_language_detector.assess_english(sample)

    @staticmethod
    def _response_language(setting: ResponseLanguage, source_language: str) -> str:
        if setting == ResponseLanguage.ENGLISH:
            return "English"
        return response_language_name(source_language)

    @staticmethod
    def _bypass(
        analysis: PromptAnalysis, reason: FallbackReason, receipt: str
    ) -> RoutingDecision:
        return RoutingDecision(
            status=DecisionStatus.BYPASSED,
            source_language=analysis.source_language,
            original_tokens=analysis.original_tokens,
            candidate_tokens=None,
            candidate_prompt=None,
            fallback_reason=reason,
            receipt=receipt,
            protected_span_count=len(analysis.protected_spans),
        )

    def _finish(
        self, request: OptimizationRequest, decision: RoutingDecision
    ) -> RoutingDecision:
        if self.recorder:
            self.recorder.record_decision(request, decision)
        return decision
