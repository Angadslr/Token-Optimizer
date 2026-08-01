from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

from slashtoken.codex.app_server import CodexAppServerClient, CodexAppServerError
from slashtoken.core.models import WorkloadMode


class CodexAppServerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_handshake_models_thread_turn_and_stream(self):
        fixture = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"
        client = CodexAppServerClient((sys.executable, str(fixture)))
        await client.start()
        try:
            models = await client.list_models()
            self.assertEqual(models[0]["id"], "fake-model")
            thread_id = await client.start_thread(
                cwd=str(Path.cwd()),
                model="fake-model",
                output_optimization=False,
                workload_mode=WorkloadMode.AGENTIC_CODING,
            )
            resumed_id = await client.resume_thread(
                thread_id=thread_id,
                cwd=str(Path.cwd()),
                model="fake-model",
                output_optimization=True,
                workload_mode=WorkloadMode.CHATBOT,
            )
            self.assertEqual(resumed_id, thread_id)
            turn_id = await client.start_turn(
                thread_id=thread_id,
                selected_prompt="approved only",
                model="fake-model",
            )
            events = []
            async for event in client.notifications(turn_id=turn_id):
                events.append(event)
                if event.get("method") == "item/commandExecution/requestApproval":
                    await client.respond(event["id"], {"decision": "accept"})
            self.assertTrue(
                any(
                    event.get("method") == "item/commandExecution/requestApproval"
                    for event in events
                )
            )
            self.assertEqual(events[-1]["method"], "turn/completed")
            self.assertTrue(
                any(event.get("method") == "serverRequest/resolved" for event in events)
            )
            self.assertEqual(client.pending_server_requests, {})
            await client.interrupt_turn(thread_id=thread_id, turn_id=turn_id)
        finally:
            await client.close()

    async def test_server_request_id_cannot_consume_client_response(self):
        client = self._client("id_collision")
        await client.start()
        try:
            models = await client.list_models()
            self.assertEqual(models[0]["id"], "fake-model")
            event = await anext(client.notifications())
            self.assertEqual(event["method"], "item/commandExecution/requestApproval")
            self.assertIn(event["id"], client.pending_server_requests)
        finally:
            await client.close()

    async def test_process_exit_wakes_notification_consumer(self):
        client = self._client("exit_after_turn")
        await client.start()
        try:
            thread_id = await client.start_thread(
                cwd=str(Path.cwd()),
                model="fake-model",
                output_optimization=False,
                workload_mode=WorkloadMode.AGENTIC_CODING,
            )
            turn_id = await client.start_turn(
                thread_id=thread_id,
                selected_prompt="exit",
                model="fake-model",
            )
            with self.assertRaises(CodexAppServerError):
                async for _ in client.notifications(turn_id=turn_id):
                    pass
        finally:
            await client.close()

    async def test_invalid_json_fails_the_stream(self):
        client = self._client("invalid_json")
        await client.start()
        try:
            thread_id = await client.start_thread(
                cwd=str(Path.cwd()),
                model="fake-model",
                output_optimization=False,
                workload_mode=WorkloadMode.AGENTIC_CODING,
            )
            turn_id = await client.start_turn(
                thread_id=thread_id,
                selected_prompt="invalid",
                model="fake-model",
            )
            with self.assertRaisesRegex(CodexAppServerError, "invalid JSON"):
                async for _ in client.notifications(turn_id=turn_id):
                    pass
        finally:
            await client.close()

    async def test_request_timeout_is_bounded(self):
        client = self._client("no_initialize_response", request_timeout_seconds=0.05)
        try:
            with self.assertRaisesRegex(CodexAppServerError, "initialize"):
                await client.start()
        finally:
            await client.close()

    def _client(
        self, mode: str, *, request_timeout_seconds: float = 1.0
    ) -> CodexAppServerClient:
        fixture = Path(__file__).parent / "fixtures" / "fake_codex_app_server.py"
        return CodexAppServerClient(
            (sys.executable, str(fixture), mode),
            request_timeout_seconds=request_timeout_seconds,
        )


if __name__ == "__main__":
    unittest.main()
