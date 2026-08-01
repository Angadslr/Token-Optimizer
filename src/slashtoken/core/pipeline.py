"""End-to-end prompt analysis and verified optimization orchestration."""

from __future__ import annotations

from typing import Protocol

from slashtoken.core.models import (
    DecisionStatus,
    FallbackReason,
    OptimizationRequest,
    PromptAnalysis,
    ResponseLanguage,
    RoutingDecision,
    VerificationResult,
)
from slashtoken.core.protection import extract_protected_spans, missing_protected_spans
from slashtoken.core.risk import SUPPORTED_LANGUAGES, classify_risk, detect_language
from slashtoken.core.routing import ThresholdRegistry
from slashtoken.providers.base import OptimizationProvider, TokenCounter


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
    ) -> None:
        self.provider = provider
        self.token_counter = token_counter
        self.thresholds = thresholds or ThresholdRegistry()
        self.recorder = recorder
        self.minimum_source_tokens = minimum_source_tokens

    def analyze(self, request: OptimizationRequest) -> PromptAnalysis:
        prompt = request.normalized_prompt()
        language = detect_language(prompt)
        risk = classify_risk(prompt)
        spans = extract_protected_spans(prompt)
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

        response_language = self._response_language(request.response_language, analysis.source_language)
        try:
            transformed = self.provider.transform(
                source_prompt=prompt,
                source_language=analysis.source_language,
                response_language=response_language,
                protected_spans=analysis.protected_spans,
            )
            candidate_tokens = self.token_counter.count(transformed.text, request.target_model)
            threshold = self.thresholds.get(analysis.source_language, request.target_model)

            if candidate_tokens.tokens >= analysis.original_tokens.tokens:
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=transformed.text,
                        fallback_reason=FallbackReason.NO_TOKEN_SAVINGS,
                        receipt="The candidate did not reduce target-model input tokens; use the original prompt.",
                        stage_usage=(transformed.usage,),
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
                        candidate_prompt=transformed.text,
                        fallback_reason=FallbackReason.BELOW_BREAK_EVEN,
                        receipt=(
                            "The candidate reduced tokens but did not meet the configured "
                            "minimum-savings threshold; use the original prompt."
                        ),
                        stage_usage=(transformed.usage,),
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            missing = missing_protected_spans(transformed.text, analysis.protected_spans)
            if missing:
                kinds = ", ".join(sorted({span.kind for span in missing}))
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=transformed.text,
                        fallback_reason=FallbackReason.PROTECTED_SPAN_MISMATCH,
                        receipt=f"Candidate rejected because protected {kinds} content changed or disappeared.",
                        stage_usage=(transformed.usage,),
                        protected_span_count=len(analysis.protected_spans),
                        threshold_version=threshold.version,
                    ),
                )

            verification = self.provider.verify(
                source_prompt=prompt,
                candidate_prompt=transformed.text,
                source_language=analysis.source_language,
                response_language=response_language,
            )
            stage_usage = (transformed.usage, verification.usage)
            if not verification.valid:
                return self._finish(
                    request,
                    RoutingDecision(
                        status=DecisionStatus.REJECTED,
                        source_language=analysis.source_language,
                        original_tokens=analysis.original_tokens,
                        candidate_tokens=candidate_tokens,
                        candidate_prompt=transformed.text,
                        fallback_reason=FallbackReason.VERIFICATION_FAILED,
                        receipt=f"Semantic verification rejected the candidate: {verification.reason}",
                        verification=verification,
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
                    candidate_prompt=transformed.text,
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
                    stage_usage=stage_usage,
                    protected_span_count=len(analysis.protected_spans),
                    auto_run_eligible=auto_eligible,
                    threshold_version=threshold.version,
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
                    receipt=f"Hosted optimization failed; no prompt was submitted. {type(error).__name__}: {error}",
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
        candidate_tokens = self.token_counter.count(candidate, request.target_model)
        threshold = self.thresholds.get(analysis.source_language, request.target_model)
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
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        missing = missing_protected_spans(candidate, analysis.protected_spans)
        if missing:
            return self._finish(
                request,
                RoutingDecision(
                    status=DecisionStatus.REJECTED,
                    source_language=analysis.source_language,
                    original_tokens=analysis.original_tokens,
                    candidate_tokens=candidate_tokens,
                    candidate_prompt=candidate,
                    fallback_reason=FallbackReason.PROTECTED_SPAN_MISMATCH,
                    receipt="Edited candidate changed or removed protected content.",
                    protected_span_count=len(analysis.protected_spans),
                    threshold_version=threshold.version,
                ),
            )
        response_language = self._response_language(request.response_language, analysis.source_language)
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
