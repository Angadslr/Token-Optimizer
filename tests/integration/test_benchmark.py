from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from slashtoken.benchmarking import run_benchmark
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.runtime import DecisionCache, SlashTokenRuntime
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from tests.helpers import CharacterTokenCounter, FakeProvider, MultilingualTokenCounter


class BenchmarkTests(unittest.TestCase):
    def test_dry_run_is_reproducible_and_content_free(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SlashTokenDatabase(Path(directory) / "bench.sqlite3")
            repository = SlashTokenRepository(database)
            provider = FakeProvider()
            runtime = SlashTokenRuntime(
                database=database,
                repository=repository,
                settings=SettingsResolver(repository),
                provider=provider,
                pipeline=OptimizationPipeline(
                    provider=provider, token_counter=CharacterTokenCounter()
                ),
                decisions=DecisionCache(),
            )
            fixtures = Path(__file__).resolve().parents[2] / "benchmarks" / "fixtures" / "prompts.jsonl"
            first = run_benchmark(runtime, fixture_path=fixtures, target_model="test", dry_run=True)
            second = run_benchmark(runtime, fixture_path=fixtures, target_model="test", dry_run=True)
            self.assertEqual(first, second)
            self.assertEqual(first["fixture_count"], 6)
            self.assertNotIn("process_batch", str(first))

    def test_explicit_benchmark_compares_final_answers_without_returning_content(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture_path = Path(directory) / "fixture.jsonl"
            fixture_path.write_text(
                json.dumps(
                    {
                        "id": "zh-synthetic-001",
                        "language": "zh",
                        "category": "coding",
                        "workload_mode": "agentic_coding",
                        "prompt": "请详细分析这个服务中的并发错误，并用中文提供完整修复、测试、风险和回滚步骤。",
                        "expected_eligible": True,
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            database = SlashTokenDatabase(Path(directory) / "full.sqlite3")
            repository = SlashTokenRepository(database)
            provider = FakeProvider(
                candidate="Analyze concurrency. Reply Chinese with full fix tests risks rollback."
            )
            runtime = SlashTokenRuntime(
                database=database,
                repository=repository,
                settings=SettingsResolver(repository),
                provider=provider,
                pipeline=OptimizationPipeline(
                    provider=provider,
                    token_counter=MultilingualTokenCounter(),
                    recorder=repository,
                    minimum_source_tokens=1,
                ),
                decisions=DecisionCache(),
            )

            report = run_benchmark(
                runtime,
                fixture_path=fixture_path,
                target_model="test",
                dry_run=False,
            )

            self.assertEqual(provider.chat_calls, 2)
            self.assertEqual(provider.comparison_calls, 1)
            self.assertTrue(report["cases"][0]["answer_evaluation"]["acceptable"])
            self.assertNotIn("并发错误", str(report))


if __name__ == "__main__":
    unittest.main()
