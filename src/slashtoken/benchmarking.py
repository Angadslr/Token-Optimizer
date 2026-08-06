"""Reproducible, content-authorized benchmark runner."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from slashtoken.core.models import (
    DecisionStatus,
    FallbackReason,
    OptimizationRequest,
    StageUsage,
    WorkloadMode,
)
from slashtoken.core.pipeline import response_language_name
from slashtoken.runtime import SlashTokenRuntime


def load_fixtures(path: str | Path) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    with Path(path).open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict) or not isinstance(payload.get("prompt"), str):
                raise ValueError(f"Invalid benchmark fixture on line {line_number}.")
            fixtures.append(payload)
    return fixtures


def run_benchmark(
    runtime: SlashTokenRuntime,
    *,
    fixture_path: str | Path,
    target_model: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    fixtures = load_fixtures(fixture_path)
    routes: Counter[str] = Counter()
    by_language: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "cases": 0,
            "original_tokens": 0,
            "candidate_tokens": 0,
            "token_savings": 0,
            "baseline_target_input_tokens": 0,
            "baseline_target_output_tokens": 0,
            "optimized_target_input_tokens": 0,
            "optimized_target_output_tokens": 0,
            "evaluated_answers": 0,
            "acceptable_answers": 0,
            "quality_score_total": 0.0,
        }
    )
    cases: list[dict[str, Any]] = []
    false_positive_count = 0
    expected_ineligible_count = 0
    priced_comparisons = 0
    baseline_cost_usd = 0.0
    optimized_cost_usd = 0.0
    net_savings_usd = 0.0
    total_optimizer_latency_ms = 0.0
    total_baseline_latency_ms = 0.0
    total_optimized_latency_ms = 0.0
    total_evaluator_latency_ms = 0.0
    benchmark_settings = runtime.settings.resolve()
    for fixture in fixtures:
        request = OptimizationRequest(
            prompt=fixture["prompt"],
            target_model=target_model,
            project_path=None,
            workload_mode=WorkloadMode(fixture.get("workload_mode", "agentic_coding")),
        )
        if dry_run:
            analysis = runtime.pipeline.analyze(request)
            status = "analysis_only"
            candidate_tokens = analysis.original_tokens.tokens
            source_language = analysis.source_language
            original_tokens = analysis.original_tokens.tokens
            savings = 0
            case_result = {
                "fixture_id": fixture.get("id"),
                "language": source_language,
                "category": fixture.get("category", "unspecified"),
                "status": status,
                "original_prompt_tokens": original_tokens,
                "candidate_prompt_tokens": candidate_tokens,
                "prompt_token_savings": savings,
            }
        else:
            decision = runtime.pipeline.optimize(request)
            status = decision.status.value
            candidate_tokens = (
                decision.candidate_tokens.tokens
                if decision.candidate_tokens
                else decision.original_tokens.tokens
            )
            source_language = decision.source_language
            original_tokens = decision.original_tokens.tokens
            savings = decision.token_savings
            response_language = response_language_name(source_language)
            baseline = runtime.provider.chat(
                prompt=request.normalized_prompt(),
                response_language=response_language,
                workload_mode=request.workload_mode,
                output_optimization=benchmark_settings.output_optimization,
            )
            total_optimizer_latency_ms += sum(
                usage.latency_ms for usage in decision.stage_usage
            )
            total_baseline_latency_ms += baseline.usage.latency_ms
            case_result = {
                "fixture_id": fixture.get("id"),
                "language": source_language,
                "category": fixture.get("category", "unspecified"),
                "status": status,
                "fallback_reason": (
                    decision.fallback_reason.value if decision.fallback_reason else None
                ),
                "original_prompt_tokens": original_tokens,
                "candidate_prompt_tokens": candidate_tokens,
                "prompt_token_savings": savings,
                "protected_span_count": decision.protected_span_count,
                "protected_spans_preserved": (
                    decision.fallback_reason
                    != FallbackReason.PROTECTED_SPAN_MISMATCH
                ),
                "prompt_verification_passed": bool(
                    decision.verification and decision.verification.valid
                ),
                "candidate_language": (
                    {
                        "detected_language": decision.candidate_language.detected_language,
                        "confidence": decision.candidate_language.confidence,
                        "reliable": decision.candidate_language.reliable,
                        "detector": decision.candidate_language.detector,
                        "latency_ms": decision.candidate_language.latency_ms,
                    }
                    if decision.candidate_language
                    else None
                ),
                "optimizer": _stage_totals(decision.stage_usage),
                "baseline_target": _usage_dict(baseline.usage),
                "optimized_target": None,
                "answer_evaluation": None,
                "production_cost_comparison": None,
            }
            bucket = by_language[source_language]
            bucket["baseline_target_input_tokens"] += baseline.usage.input_tokens
            bucket["baseline_target_output_tokens"] += baseline.usage.output_tokens

            if decision.status == DecisionStatus.CANDIDATE and decision.candidate_prompt:
                optimized = runtime.provider.chat(
                    prompt=decision.candidate_prompt,
                    response_language=response_language,
                    workload_mode=request.workload_mode,
                    output_optimization=benchmark_settings.output_optimization,
                )
                evaluation = runtime.provider.compare_answers(
                    source_prompt=request.normalized_prompt(),
                    baseline_answer=baseline.response,
                    optimized_answer=optimized.response,
                    source_language=source_language,
                )
                total_optimized_latency_ms += optimized.usage.latency_ms
                total_evaluator_latency_ms += evaluation.usage.latency_ms
                bucket["optimized_target_input_tokens"] += optimized.usage.input_tokens
                bucket["optimized_target_output_tokens"] += optimized.usage.output_tokens
                bucket["evaluated_answers"] += 1
                bucket["acceptable_answers"] += int(evaluation.acceptable)
                bucket["quality_score_total"] += evaluation.quality_score
                case_result["optimized_target"] = _usage_dict(optimized.usage)
                case_result["answer_evaluation"] = {
                    "acceptable": evaluation.acceptable,
                    "quality_score": evaluation.quality_score,
                    "preserves_constraints": evaluation.preserves_constraints,
                    "evaluator_usage": _usage_dict(evaluation.usage),
                }
                production_stages = (*decision.stage_usage, optimized.usage)
                costs_available = bool(
                    baseline.usage.pricing_available
                    and production_stages
                    and all(stage.pricing_available for stage in production_stages)
                )
                baseline_cost = baseline.usage.estimated_cost_usd
                optimized_cost = sum(
                    stage.estimated_cost_usd for stage in production_stages
                )
                case_result["production_cost_comparison"] = {
                    "available": costs_available,
                    "baseline_cost_usd": baseline_cost if costs_available else None,
                    "optimized_cost_usd": optimized_cost if costs_available else None,
                    "net_savings_usd": (
                        baseline_cost - optimized_cost if costs_available else None
                    ),
                }
                if costs_available:
                    priced_comparisons += 1
                    baseline_cost_usd += baseline_cost
                    optimized_cost_usd += optimized_cost
                    net_savings_usd += baseline_cost - optimized_cost

            expected_eligible = bool(fixture.get("expected_eligible", True))
            expected_ineligible_count += int(not expected_eligible)
            if decision.status == DecisionStatus.CANDIDATE and not expected_eligible:
                false_positive_count += 1
        routes[status] += 1
        bucket = by_language[source_language]
        bucket["cases"] += 1
        bucket["original_tokens"] += original_tokens
        bucket["candidate_tokens"] += candidate_tokens
        bucket["token_savings"] += savings
        cases.append(case_result)
    language_report = dict(by_language)
    for bucket in language_report.values():
        evaluated = bucket["evaluated_answers"]
        bucket["answer_acceptance_rate"] = (
            bucket["acceptable_answers"] / evaluated if evaluated else None
        )
        bucket["mean_quality_score"] = (
            bucket["quality_score_total"] / evaluated if evaluated else None
        )
        del bucket["quality_score_total"]
    return {
        "fixture_count": len(fixtures),
        "target_model": target_model,
        "dry_run": dry_run,
        "routes": dict(routes),
        "by_language": language_report,
        "cases": cases,
        "false_positive_count": false_positive_count,
        "false_positive_rate": (
            false_positive_count / expected_ineligible_count
            if expected_ineligible_count
            else None
        ),
        "candidate_rate": (
            routes[DecisionStatus.CANDIDATE.value] / len(fixtures) if fixtures else 0.0
        ),
        "bypass_rate": (
            routes[DecisionStatus.BYPASSED.value] / len(fixtures) if fixtures else 0.0
        ),
        "cost_summary": {
            "priced_comparisons": priced_comparisons,
            "baseline_cost_usd": baseline_cost_usd if priced_comparisons else None,
            "optimized_cost_usd": optimized_cost_usd if priced_comparisons else None,
            "net_savings_usd": net_savings_usd if priced_comparisons else None,
        },
        "latency_summary_ms": {
            "optimizer": total_optimizer_latency_ms,
            "baseline_target": total_baseline_latency_ms,
            "optimized_target": total_optimized_latency_ms,
            "benchmark_evaluator": total_evaluator_latency_ms,
        },
        "privacy": "No raw prompt content is included in this report.",
    }


def _usage_dict(usage: StageUsage) -> dict[str, Any]:
    return {
        "stage": usage.stage,
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "output_tokens": usage.output_tokens,
        "estimated_cost_usd": (
            usage.estimated_cost_usd if usage.pricing_available else None
        ),
        "pricing_available": usage.pricing_available,
        "latency_ms": usage.latency_ms,
    }


def _stage_totals(stages: Iterable[StageUsage]) -> dict[str, Any]:
    stages = tuple(stages)
    return {
        "input_tokens": sum(stage.input_tokens for stage in stages),
        "cached_input_tokens": sum(stage.cached_input_tokens for stage in stages),
        "output_tokens": sum(stage.output_tokens for stage in stages),
        "estimated_cost_usd": (
            sum(stage.estimated_cost_usd for stage in stages)
            if stages and all(stage.pricing_available for stage in stages)
            else None
        ),
        "pricing_available": bool(
            stages and all(stage.pricing_available for stage in stages)
        ),
        "latency_ms": sum(stage.latency_ms for stage in stages),
    }
