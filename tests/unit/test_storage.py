from __future__ import annotations

import tempfile
import unittest
import sqlite3
from pathlib import Path

from slashtoken.core.models import OptimizationRequest
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from tests.helpers import CharacterTokenCounter, FakeProvider


class StorageTests(unittest.TestCase):
    def test_existing_database_receives_forward_schema_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.execute(
                """
                CREATE TABLE routing_decisions (
                    decision_id TEXT PRIMARY KEY,
                    prompt_hash TEXT NOT NULL,
                    source_language TEXT NOT NULL,
                    target_model TEXT NOT NULL,
                    workload_mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    original_tokens INTEGER NOT NULL,
                    token_savings INTEGER NOT NULL,
                    tokenizer TEXT NOT NULL,
                    optimizer_cost_usd REAL NOT NULL,
                    latency_ms REAL NOT NULL,
                    protected_span_count INTEGER NOT NULL,
                    auto_run_eligible INTEGER NOT NULL,
                    threshold_version TEXT NOT NULL
                )
                """
            )
            connection.commit()
            connection.close()

            database = SlashTokenDatabase(path)
            with database.session() as migrated:
                columns = {
                    row["name"]
                    for row in migrated.execute(
                        "PRAGMA table_info(routing_decisions)"
                    )
                }
                codex_runs = migrated.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'codex_runs'"
                ).fetchone()

            self.assertIn("optimizer_cost_available", columns)
            self.assertIn("candidate_language", columns)
            self.assertIn("candidate_language_confidence", columns)
            self.assertIn("candidate_language_reliable", columns)
            self.assertIn("candidate_language_detector", columns)
            self.assertIn("candidate_language_latency_ms", columns)
            self.assertIsNotNone(codex_runs)

    def test_database_never_contains_prompt_or_candidate_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "privacy.sqlite3"
            repository = SlashTokenRepository(SlashTokenDatabase(path))
            source = "请分析这个绝密系统的并发错误并给出完整修复和测试。"
            candidate = "Analyze confidential concurrency. Reply Chinese with full fix and tests."
            pipeline = OptimizationPipeline(
                provider=FakeProvider(candidate=candidate),
                token_counter=CharacterTokenCounter(),
                recorder=repository,
                minimum_source_tokens=1,
            )
            decision = pipeline.optimize(
                OptimizationRequest(prompt=source, target_model="test")
            )
            private_project = "/private/confidential-project"
            repository.create_codex_run(
                run_id="run-safe",
                decision_id=decision.decision_id,
                model="test",
                project_path=private_project,
            )
            repository.update_codex_run_identity(
                run_id="run-safe", thread_id="thread-safe", turn_id="turn-safe"
            )
            repository.update_codex_run_usage(
                run_id="run-safe",
                usage={
                    "thread_total": {"total_tokens": 100},
                    "last_call": {"total_tokens": 40},
                    "run_total": {"total_tokens": 100},
                    "model_context_window": 258400,
                },
            )
            repository.update_codex_run_status(
                run_id="run-safe", status="failed", failure_code="turn_failed"
            )
            raw = path.read_bytes()
            self.assertNotIn(source.encode("utf-8"), raw)
            self.assertNotIn(candidate.encode("utf-8"), raw)
            self.assertNotIn(private_project.encode("utf-8"), raw)
            self.assertEqual(repository.usage_summary()["requests"], 1)
            self.assertEqual(repository.get_codex_run("run-safe")["status"], "failed")
            with repository.database.session() as connection:
                language = connection.execute(
                    """
                    SELECT candidate_language, candidate_language_reliable,
                           candidate_language_detector
                    FROM routing_decisions
                    WHERE decision_id = ?
                    """,
                    (decision.decision_id,),
                ).fetchone()
            self.assertEqual(language["candidate_language"], "en")
            self.assertEqual(language["candidate_language_reliable"], 1)
            self.assertIn("detector", language["candidate_language_detector"])


if __name__ == "__main__":
    unittest.main()
