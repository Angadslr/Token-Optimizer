from __future__ import annotations

import unittest

from slashtoken.core.models import DecisionStatus, FallbackReason, OptimizationRequest
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.core.routing import RoutingThreshold, ThresholdRegistry
from slashtoken.providers.base import ProviderUnavailableError
from tests.helpers import MultilingualTokenCounter, FakeProvider


LONG_CHINESE = "请详细分析这个软件服务中的并发错误，并用中文给出完整修复、测试、风险和回滚步骤，不要遗漏任何要求。"


class PipelineTests(unittest.TestCase):
    def request(self, prompt: str = LONG_CHINESE) -> OptimizationRequest:
        return OptimizationRequest(prompt=prompt, target_model="test-model")

    def test_verified_candidate_is_returned_but_uncalibrated_auto_run_is_off(self):
        provider = FakeProvider(candidate="Analyze concurrency. Reply in Chinese with fix, tests, risks, rollback.")
        pipeline = OptimizationPipeline(
            provider=provider,
            token_counter=MultilingualTokenCounter(),
            minimum_source_tokens=1,
        )
        decision = pipeline.optimize(self.request())
        self.assertEqual(decision.status, DecisionStatus.CANDIDATE)
        self.assertGreater(decision.token_savings, 0)
        self.assertFalse(decision.auto_run_eligible)
        self.assertEqual(provider.transform_calls, 1)
        self.assertEqual(provider.verify_calls, 1)

    def test_temporary_provider_failure_bypasses_to_original(self):
        class UnavailableProvider(FakeProvider):
            def transform(self, **kwargs):
                raise ProviderUnavailableError(
                    stage="prompt_transformation", status_code=529
                )

        pipeline = OptimizationPipeline(
            provider=UnavailableProvider(candidate="unused"),
            token_counter=MultilingualTokenCounter(),
            minimum_source_tokens=1,
        )

        decision = pipeline.optimize(self.request())

        self.assertEqual(decision.status, DecisionStatus.BYPASSED)
        self.assertEqual(
            decision.fallback_reason,
            FallbackReason.PROVIDER_UNAVAILABLE,
        )
        self.assertIsNone(decision.candidate_prompt)
        self.assertIn("original-language prompt is ready", decision.receipt)
        self.assertIn("Output optimization will still apply", decision.receipt)
        self.assertNotIn("529", decision.receipt)

    def test_temporary_verification_failure_discards_unverified_candidate(self):
        class VerificationUnavailableProvider(FakeProvider):
            def verify(self, **kwargs):
                self.verify_calls += 1
                raise ProviderUnavailableError(
                    stage="semantic_verification", status_code=529
                )

        pipeline = OptimizationPipeline(
            provider=VerificationUnavailableProvider(
                candidate="Analyze concurrency. Reply Chinese with fixes and tests."
            ),
            token_counter=MultilingualTokenCounter(),
            minimum_source_tokens=1,
        )

        decision = pipeline.optimize(self.request())

        self.assertEqual(decision.status, DecisionStatus.BYPASSED)
        self.assertEqual(
            decision.fallback_reason,
            FallbackReason.PROVIDER_UNAVAILABLE,
        )
        self.assertIsNone(decision.candidate_prompt)
        self.assertEqual(len(decision.stage_usage), 1)
        self.assertEqual(decision.stage_usage[0].stage, "prompt_transformation")

    def test_calibrated_exact_threshold_enables_auto_run(self):
        provider = FakeProvider(candidate="Analyze concurrency. Reply Chinese. Include fix tests risks rollback.")
        thresholds = ThresholdRegistry(
            (
                RoutingThreshold(
                    language="zh",
                    model="test-model",
                    minimum_tokens_saved=5,
                    minimum_percent_saved=5,
                    calibrated=True,
                    version="zh-test-v1",
                ),
            )
        )
        pipeline = OptimizationPipeline(
            provider=provider,
            token_counter=MultilingualTokenCounter(),
            thresholds=thresholds,
            minimum_source_tokens=1,
        )
        decision = pipeline.optimize(self.request())
        self.assertTrue(decision.auto_run_eligible)
        self.assertEqual(decision.threshold_version, "zh-test-v1")

    def test_high_stakes_prompt_never_calls_transformer(self):
        provider = FakeProvider(candidate="unused")
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        decision = pipeline.optimize(self.request("请给出这个症状的诊断和药物剂量。"))
        self.assertEqual(decision.fallback_reason, FallbackReason.HIGH_STAKES)
        self.assertIn("bypassed", decision.receipt)
        self.assertEqual(provider.transform_calls, 0)

    def test_unsupported_language_falls_back_without_provider_call(self):
        provider = FakeProvider(candidate="unused")
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        decision = pipeline.optimize(self.request("¿Puede analizar este error de concurrencia?"))
        self.assertEqual(decision.fallback_reason, FallbackReason.UNSUPPORTED_LANGUAGE)
        self.assertEqual(provider.transform_calls, 0)

    def test_no_savings_skips_semantic_verifier(self):
        provider = FakeProvider(candidate=LONG_CHINESE + LONG_CHINESE)
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        decision = pipeline.optimize(self.request())
        self.assertEqual(decision.fallback_reason, FallbackReason.NO_TOKEN_SAVINGS)
        self.assertEqual(provider.verify_calls, 0)

    def test_below_calibrated_savings_threshold_skips_semantic_verifier(self):
        provider = FakeProvider(
            candidate="Analyze concurrency. Reply Chinese with fix tests risks rollback."
        )
        thresholds = ThresholdRegistry(
            (
                RoutingThreshold(
                    language="zh",
                    model="test-model",
                    minimum_tokens_saved=10_000,
                    minimum_percent_saved=99,
                    calibrated=True,
                    version="strict-v1",
                ),
            )
        )
        pipeline = OptimizationPipeline(
            provider=provider,
            token_counter=MultilingualTokenCounter(),
            thresholds=thresholds,
            minimum_source_tokens=1,
        )

        decision = pipeline.optimize(self.request())

        self.assertEqual(decision.fallback_reason, FallbackReason.BELOW_BREAK_EVEN)
        self.assertEqual(provider.verify_calls, 0)

    def test_protected_span_loss_rejects_before_verifier(self):
        prompt = "请分析 ERR-2048 和 `process_batch` 中的错误，并用中文给出完整测试和修复。"
        provider = FakeProvider(candidate="Analyze the error and reply in Chinese with full tests and fix.")
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        decision = pipeline.optimize(self.request(prompt))
        self.assertEqual(decision.fallback_reason, FallbackReason.PROTECTED_SPAN_MISMATCH)
        self.assertIsNone(decision.candidate_prompt)
        self.assertEqual(provider.verify_calls, 0)

    def test_protected_values_are_restored_before_counting_and_verification(self):
        prompt = "请分析 ERR-2048 和 5000 的限制，并用中文给出完整测试和修复。"

        class PlaceholderPreservingProvider(FakeProvider):
            def transform(self, **kwargs):
                first, second = (span.value for span in kwargs["protected_spans"])
                self.candidate = (
                    f"Analyze {first} with limit {second}. Reply Chinese with tests and fix."
                )
                return super().transform(**kwargs)

            def verify(self, **kwargs):
                self.verified_candidate = kwargs["candidate_prompt"]
                return super().verify(**kwargs)

        provider = PlaceholderPreservingProvider()
        pipeline = OptimizationPipeline(
            provider=provider,
            token_counter=MultilingualTokenCounter(),
            minimum_source_tokens=1,
        )

        decision = pipeline.optimize(self.request(prompt))

        self.assertEqual(decision.status, DecisionStatus.CANDIDATE)
        self.assertIn("ERR-2048", decision.candidate_prompt)
        self.assertIn("5000", decision.candidate_prompt)
        self.assertNotIn("__STP_", decision.candidate_prompt)
        self.assertEqual(provider.verified_candidate, decision.candidate_prompt)

    def test_semantic_verification_failure_rejects_candidate(self):
        provider = FakeProvider(
            candidate="Analyze concurrency and reply in Chinese.", verification_valid=False
        )
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        decision = pipeline.optimize(self.request())
        self.assertEqual(decision.fallback_reason, FallbackReason.VERIFICATION_FAILED)

    def test_edited_candidate_runs_all_post_transform_gates(self):
        prompt = "请分析 ERR-2048 的错误并提供完整修复、测试和风险，使用中文回答。"
        provider = FakeProvider(candidate="Analyze ERR-2048. Reply Chinese with full fix tests risks.")
        pipeline = OptimizationPipeline(
            provider=provider, token_counter=MultilingualTokenCounter(), minimum_source_tokens=1
        )
        revised = pipeline.reverify_candidate(
            self.request(prompt), "Analyze the error. Reply Chinese."
        )
        self.assertEqual(revised.fallback_reason, FallbackReason.PROTECTED_SPAN_MISMATCH)
        self.assertEqual(provider.verify_calls, 0)


if __name__ == "__main__":
    unittest.main()
