from __future__ import annotations

import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

from slashtoken.codex.app_server import CodexAppServerClient
from slashtoken.codex.runs import CodexRunConfig, CodexRunManager
from slashtoken.core.models import OptimizationRequest
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.runtime import DecisionCache, SlashTokenRuntime
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from tests.helpers import FakeProvider, MultilingualTokenCounter


class CodexRunManagerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = SlashTokenDatabase(Path(self.temp.name) / "runs.sqlite3")
        repository = SlashTokenRepository(database)
        provider = FakeProvider(candidate="Analyze the synthetic task completely.")
        self.runtime = SlashTokenRuntime(
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
        self.managers: list[CodexRunManager] = []

    async def asyncTearDown(self):
        for manager in self.managers:
            await manager.close()
        self.temp.cleanup()

    async def test_reload_restores_pending_approval_and_run_completes(self):
        manager = self._manager("repeated")
        queue, snapshot = await manager.attach(
            session_id="browser-reload", requested_run_id=None
        )
        self.assertIsNone(snapshot)
        decision_id = self._decision()
        run_id = await manager.submit(
            session_id="browser-reload",
            decision_id=decision_id,
            selection="original",
            edited_prompt=None,
            resume_thread_id=None,
        )
        first = await self._message(queue, "approval_required")
        self.assertEqual(first["approval"]["request_id"], 900)

        await manager.detach(session_id="browser-reload", queue=queue)
        reloaded_queue, restored = await manager.attach(
            session_id="browser-reload", requested_run_id="stale-previous-run"
        )
        self.assertEqual(restored["run"]["run_id"], run_id)
        self.assertEqual(restored["run"]["status"], "waiting_for_approval")
        self.assertEqual(restored["run"]["pending_approvals"][0]["request_id"], 900)

        await manager.respond_to_approval(
            session_id="browser-reload",
            run_id=run_id,
            request_id=900,
            decision="accept",
        )
        await self._message(reloaded_queue, "approval_resolved")
        second = await self._message(reloaded_queue, "approval_required")
        self.assertEqual(second["approval"]["request_id"], 901)
        await manager.respond_to_approval(
            session_id="browser-reload",
            run_id=run_id,
            request_id=901,
            decision="acceptForSession",
        )
        completed = await self._message(reloaded_queue, "turn_complete")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["usage"]["run_total"]["total_tokens"], 140)
        persisted = self.runtime.repository.get_codex_run(run_id)
        self.assertEqual(persisted["status"], "completed")
        self.assertEqual(persisted["usage"]["thread_total"]["total_tokens"], 140)

    async def test_unanswered_approval_cancels_and_interrupts(self):
        manager = self._manager(
            "unresolved",
            config=CodexRunConfig(
                approval_timeout_seconds=0.02,
                disconnected_grace_seconds=1,
                approval_resolution_seconds=0.02,
                interrupt_timeout_seconds=0.2,
                silence_warning_seconds=0.05,
            ),
        )
        queue, _ = await manager.attach(
            session_id="browser-timeout", requested_run_id=None
        )
        run_id = await manager.submit(
            session_id="browser-timeout",
            decision_id=self._decision(),
            selection="original",
            edited_prompt=None,
            resume_thread_id=None,
        )
        await self._message(queue, "approval_required")
        completed = await self._message(queue, "turn_complete", timeout=1)
        self.assertEqual(completed["status"], "interrupted")
        self.assertEqual(self.runtime.repository.get_codex_run(run_id)["status"], "interrupted")

    async def test_failed_turn_is_not_reported_as_complete(self):
        manager = self._manager("failed")
        queue, _ = await manager.attach(
            session_id="browser-failed", requested_run_id=None
        )
        run_id = await manager.submit(
            session_id="browser-failed",
            decision_id=self._decision(),
            selection="original",
            edited_prompt=None,
            resume_thread_id=None,
        )
        completed = await self._message(queue, "turn_complete")
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["failure_code"], "codex_serverOverloaded")
        self.assertEqual(self.runtime.repository.get_codex_run(run_id)["status"], "failed")

    async def test_process_exit_becomes_terminal_failure(self):
        manager = self._manager("exit_after_turn")
        queue, _ = await manager.attach(
            session_id="browser-exit", requested_run_id=None
        )
        await manager.submit(
            session_id="browser-exit",
            decision_id=self._decision(),
            selection="original",
            edited_prompt=None,
            resume_thread_id=None,
        )
        completed = await self._message(queue, "turn_complete")
        self.assertEqual(completed["status"], "failed")
        self.assertEqual(completed["failure_code"], "codex_app_server_error")

    async def test_resolved_approval_rejects_duplicate_response(self):
        manager = self._manager("normal")
        queue, _ = await manager.attach(
            session_id="browser-duplicate", requested_run_id=None
        )
        run_id = await manager.submit(
            session_id="browser-duplicate",
            decision_id=self._decision(),
            selection="original",
            edited_prompt=None,
            resume_thread_id=None,
        )
        approval = await self._message(queue, "approval_required")
        request_id = approval["approval"]["request_id"]
        await manager.respond_to_approval(
            session_id="browser-duplicate",
            run_id=run_id,
            request_id=request_id,
            decision="accept",
        )
        await self._message(queue, "approval_resolved")
        with self.assertRaisesRegex(ValueError, "stale"):
            await manager.respond_to_approval(
                session_id="browser-duplicate",
                run_id=run_id,
                request_id=request_id,
                decision="accept",
            )

    def _manager(
        self, mode: str, *, config: CodexRunConfig | None = None
    ) -> CodexRunManager:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"
        manager = CodexRunManager(
            self.runtime,
            client_factory=lambda: CodexAppServerClient(
                (sys.executable, str(fixture), mode), request_timeout_seconds=0.5
            ),
            config=config or CodexRunConfig(disconnected_grace_seconds=1),
        )
        self.managers.append(manager)
        return manager

    def _decision(self) -> str:
        request = OptimizationRequest(
            prompt="请完整分析这个合成任务并保留所有要求。",
            target_model="fake-model",
            project_path=self.temp.name,
        )
        decision = self.runtime.pipeline.optimize(request)
        self.runtime.decisions.put(request, decision)
        return decision.decision_id

    async def _message(
        self,
        queue: asyncio.Queue[dict],
        message_type: str,
        *,
        timeout: float = 1,
    ) -> dict:
        async with asyncio.timeout(timeout):
            while True:
                message = await queue.get()
                if message.get("type") == message_type:
                    return message


if __name__ == "__main__":
    unittest.main()
