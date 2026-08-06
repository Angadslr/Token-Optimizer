"""Composition root shared by CLI, web, MCP, and benchmarks."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from slashtoken.core.models import DecisionStatus, OptimizationRequest, RoutingDecision
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.core.routing import ThresholdRegistry
from slashtoken.providers.base import ModelPrice, PricingCatalog, TiktokenCounter
from slashtoken.providers.nvidia_deepseek import NvidiaDeepSeekProvider
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository


@dataclass(slots=True)
class PendingDecision:
    request: OptimizationRequest
    decision: RoutingDecision
    expires_at: float


class DecisionCache:
    """Short-lived prompt state kept only in process memory for approval UX."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, PendingDecision] = {}
        self._lock = threading.RLock()

    def put(self, request: OptimizationRequest, decision: RoutingDecision) -> None:
        with self._lock:
            self._purge()
            self._items[decision.decision_id] = PendingDecision(
                request=request,
                decision=decision,
                expires_at=time.monotonic() + self.ttl_seconds,
            )

    def get(self, decision_id: str) -> PendingDecision:
        with self._lock:
            self._purge()
            item = self._items.get(decision_id)
            if item is None:
                raise KeyError("Decision expired or does not exist.")
            return item

    def update(self, decision_id: str, decision: RoutingDecision) -> None:
        with self._lock:
            item = self.get(decision_id)
            self._items[decision_id] = PendingDecision(
                request=item.request,
                decision=decision,
                expires_at=time.monotonic() + self.ttl_seconds,
            )

    def consume(self, decision_id: str) -> PendingDecision:
        with self._lock:
            item = self.get(decision_id)
            del self._items[decision_id]
            return item

    def _purge(self) -> None:
        now = time.monotonic()
        expired = [key for key, item in self._items.items() if item.expires_at <= now]
        for key in expired:
            del self._items[key]


@dataclass(slots=True)
class SlashTokenRuntime:
    database: SlashTokenDatabase
    repository: SlashTokenRepository
    settings: SettingsResolver
    provider: NvidiaDeepSeekProvider
    pipeline: OptimizationPipeline
    decisions: DecisionCache


def build_runtime(*, database_path: str | None = None) -> SlashTokenRuntime:
    from slashtoken.providers.lingua_language import LinguaCandidateLanguageDetector

    if os.environ.get("SLASHTOKEN_LOAD_DOTENV") == "1":
        try:
            from dotenv import load_dotenv
        except ImportError as error:
            raise RuntimeError(
                "Install python-dotenv or unset SLASHTOKEN_LOAD_DOTENV."
            ) from error
        load_dotenv(override=False)
    database = SlashTokenDatabase(database_path)
    repository = SlashTokenRepository(database)
    optimizer_model = os.environ.get(
        "SLASHTOKEN_OPTIMIZER_MODEL", "deepseek-ai/deepseek-v4-flash"
    )
    input_price = _optional_nonnegative_float(
        "SLASHTOKEN_OPTIMIZER_INPUT_USD_PER_MILLION"
    )
    output_price = _optional_nonnegative_float(
        "SLASHTOKEN_OPTIMIZER_OUTPUT_USD_PER_MILLION"
    )
    prices = {}
    if input_price is not None and output_price is not None:
        prices[optimizer_model] = ModelPrice(
            input_per_million_usd=input_price,
            output_per_million_usd=output_price,
        )
    pricing = PricingCatalog(prices)
    provider = NvidiaDeepSeekProvider(
        model=optimizer_model,
        pricing=pricing,
        transformation_max_tokens=_optional_positive_int_or_disabled(
            "SLASHTOKEN_TRANSFORMATION_MAX_TOKENS"
        ),
        request_timeout_seconds=_positive_float(
            "SLASHTOKEN_PROVIDER_TIMEOUT_SECONDS", 300.0
        ),
    )
    thresholds_path = os.environ.get("SLASHTOKEN_THRESHOLDS_PATH")
    thresholds = (
        ThresholdRegistry.from_json_file(thresholds_path)
        if thresholds_path
        else ThresholdRegistry()
    )
    pipeline = OptimizationPipeline(
        provider=provider,
        token_counter=TiktokenCounter(),
        thresholds=thresholds,
        recorder=repository,
        candidate_language_detector=LinguaCandidateLanguageDetector(
            minimum_confidence_margin=_unit_interval_float(
                "SLASHTOKEN_ENGLISH_CONFIDENCE_MARGIN", 0.15
            )
        ),
        protected_span_soft_limit=_nonnegative_int(
            "SLASHTOKEN_PROTECTED_SPAN_SOFT_LIMIT", 40
        ),
    )
    return SlashTokenRuntime(
        database=database,
        repository=repository,
        settings=SettingsResolver(repository),
        provider=provider,
        pipeline=pipeline,
        decisions=DecisionCache(),
    )


def _optional_nonnegative_float(name: str) -> float | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    parsed = float(value)
    if parsed < 0:
        raise ValueError(f"{name} cannot be negative.")
    return parsed


def _positive_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _unit_interval_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    parsed = default if value is None or not value.strip() else float(value)
    if not 0 <= parsed < 1:
        raise ValueError(f"{name} must be greater than or equal to 0 and less than 1.")
    return parsed


def _nonnegative_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = int(value.strip())
    if parsed < 0:
        raise ValueError(f"{name} cannot be negative.")
    return parsed


def _optional_positive_int_or_disabled(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    normalized = value.strip().casefold()
    if normalized in {"0", "none", "off", "unlimited"}:
        return None
    parsed = int(normalized)
    if parsed <= 0:
        raise ValueError(
            f"{name} must be a positive integer, 0, none, off, or unlimited."
        )
    return parsed


def select_pending_prompt(
    runtime: SlashTokenRuntime,
    *,
    decision_id: str,
    selection: str,
    edited_prompt: str | None = None,
) -> tuple[PendingDecision, str]:
    """Resolve a displayed decision into one approved prompt, reverifying edits."""
    if selection not in {"candidate", "original"}:
        raise ValueError("selection must be candidate or original.")
    pending = runtime.decisions.get(decision_id)
    if selection == "original":
        return pending, pending.request.normalized_prompt()
    candidate = pending.decision.candidate_prompt
    if candidate is None or pending.decision.status != DecisionStatus.CANDIDATE:
        raise ValueError("This decision has no verified optimization candidate.")
    if edited_prompt is not None and edited_prompt.strip() != candidate:
        revised = runtime.pipeline.reverify_candidate(pending.request, edited_prompt)
        if revised.status != DecisionStatus.CANDIDATE or revised.candidate_prompt is None:
            raise ValueError(revised.receipt)
        runtime.decisions.update(decision_id, revised)
        pending = runtime.decisions.get(decision_id)
        candidate = revised.candidate_prompt
    return pending, candidate
