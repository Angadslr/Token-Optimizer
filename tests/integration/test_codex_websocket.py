from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from slashtoken.codex.app_server import CodexAppServerClient
from slashtoken.codex.runs import CodexRunConfig, CodexRunManager
from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.runtime import DecisionCache, SlashTokenRuntime
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from slashtoken.web.app import create_app
from tests.helpers import FakeProvider, MultilingualTokenCounter


class CodexWebSocketIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = SlashTokenDatabase(Path(self.temp.name) / "socket.sqlite3")
        repository = SlashTokenRepository(database)
        provider = FakeProvider(candidate="Analyze the synthetic socket task completely.")
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
        fixture = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"
        manager = CodexRunManager(
            runtime,
            client_factory=lambda: CodexAppServerClient(
                (sys.executable, str(fixture), "normal"),
                request_timeout_seconds=0.5,
            ),
            config=CodexRunConfig(disconnected_grace_seconds=1),
        )
        self.client_context = TestClient(create_app(runtime, manager))
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.temp.cleanup()

    def test_socket_reload_restores_approval_and_finishes(self):
        decision = self.client.post(
            "/api/optimize",
            json={
                "prompt": "请完整分析这个合成任务并保留所有要求。",
                "target_model": "fake-model",
                "project_path": self.temp.name,
                "session_id": "socket-browser",
                "workload_mode": "agentic_coding",
            },
        ).json()

        with self.client.websocket_connect("/ws/codex") as socket:
            self.assertEqual(socket.receive_json()["type"], "connected")
            socket.send_json(
                {
                    "action": "attach",
                    "session_id": "socket-browser",
                    "run_id": None,
                }
            )
            self.assertEqual(socket.receive_json()["type"], "attached")
            socket.send_json(
                {
                    "action": "submit",
                    "decision_id": decision["decision_id"],
                    "selection": "original",
                    "edited_prompt": None,
                    "thread_id": None,
                }
            )
            submitted = self._receive_type(socket, "submitted")
            run_id = submitted["run_id"]
            approval = self._receive_type(socket, "approval_required")
            self.assertEqual(approval["approval"]["request_id"], 900)

        with self.client.websocket_connect("/ws/codex") as reloaded:
            self.assertEqual(reloaded.receive_json()["type"], "connected")
            reloaded.send_json(
                {
                    "action": "attach",
                    "session_id": "socket-browser",
                    "run_id": run_id,
                }
            )
            self.assertEqual(reloaded.receive_json()["type"], "attached")
            snapshot = reloaded.receive_json()
            self.assertEqual(snapshot["type"], "run_snapshot")
            self.assertEqual(snapshot["run"]["status"], "waiting_for_approval")
            reloaded.send_json(
                {
                    "action": "approval_response",
                    "run_id": run_id,
                    "request_id": 900,
                    "decision": "accept",
                }
            )
            completed = self._receive_type(reloaded, "turn_complete")
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["usage"]["thread_total"]["total_tokens"], 140)

    def _receive_type(self, socket, message_type: str) -> dict:
        for _ in range(100):
            message = socket.receive_json()
            if message.get("type") == message_type:
                return message
        self.fail(f"WebSocket did not emit {message_type}.")


if __name__ == "__main__":
    unittest.main()
