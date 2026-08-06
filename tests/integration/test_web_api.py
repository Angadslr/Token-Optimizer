from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.providers.base import ProviderUnavailableError
from slashtoken.runtime import DecisionCache, SlashTokenRuntime, select_pending_prompt
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from tests.helpers import MultilingualTokenCounter, FakeProvider


@unittest.skipUnless(httpx is not None, "FastAPI test dependencies are not installed")
class WebAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = SlashTokenDatabase(Path(self.temp.name) / "web.sqlite3")
        repository = SlashTokenRepository(database)
        provider = FakeProvider(
            candidate="Analyze concurrency. Reply Chinese with complete fix, tests, and risks."
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
        self.runtime = runtime
        from slashtoken.web.app import create_app

        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(runtime)),
            base_url="http://slashtoken.test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        self.temp.cleanup()

    async def test_root_settings_analysis_and_optimization(self):
        root = await self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("SlashToken", root.text)
        self.assertIn("codex.approvals", root.text)
        self.assertIn("codex.analytics", root.text)
        self.assertIn('aria-describedby="reasoning-effort-help"', root.text)
        self.assertIn('model_reasoning_effort = "low"', root.text)
        self.assertIn("~/.codex/config.toml", root.text)
        self.assertIn("/model", root.text)
        self.assertLess(
            root.text.index('id="reasoning-effort-help"'),
            root.text.index('id="model"'),
        )

        script = Path("src/slashtoken/web/static/app.js").read_text()
        self.assertNotIn("window.confirm", script)
        self.assertIn("sessionStorage", script)
        self.assertIn('action: "attach"', script)

        settings = (await self.client.get("/api/settings")).json()
        self.assertTrue(settings["language_optimization"])

        body = {
            "prompt": "请详细分析这个软件服务的并发错误，并用中文提供完整修复、测试和风险。",
            "target_model": "test-model",
            "workload_mode": "agentic_coding",
        }
        analysis = await self.client.post("/api/analyze", json=body)
        self.assertEqual(analysis.status_code, 200)
        self.assertEqual(analysis.json()["source_language"], "zh")

        decision = await self.client.post("/api/optimize", json=body)
        self.assertEqual(decision.status_code, 200)
        self.assertEqual(decision.json()["status"], "candidate")
        self.assertEqual(
            decision.json()["candidate_language"]["detected_language"], "en"
        )
        self.assertTrue(decision.json()["candidate_language"]["reliable"])
        self.assertFalse(decision.json()["should_auto_run"])

        self.assertIn('"lang.candidate"', script)
        self.assertIn('"lang.confidence"', script)
        self.assertIn('"lang.detector"', script)

        def unavailable_chat(**kwargs):
            raise ProviderUnavailableError(stage="target_chat", status_code=529)

        self.runtime.provider.chat = unavailable_chat
        chat = await self.client.post(
            "/api/chat",
            json={
                "decision_id": decision.json()["decision_id"],
                "selection": "original",
                "session_id": "temporary-outage-test",
            },
        )
        self.assertEqual(chat.status_code, 503)
        self.assertIn("temporarily unavailable", chat.json()["detail"])
        self.assertIn("HTTP 529", chat.json()["detail"])
        self.assertNotIn("Service temporarily overloaded", chat.json()["detail"])

    async def test_temporary_optimizer_outage_keeps_original_route_available(self):
        session_id = "temporary-optimizer-outage"
        await self.client.patch(
            "/api/settings",
            json={
                "scope": "session",
                "session_id": session_id,
                "values": {"output_optimization": True},
            },
        )

        def unavailable_transform(**kwargs):
            raise ProviderUnavailableError(
                stage="prompt_transformation", status_code=529
            )

        self.runtime.provider.transform = unavailable_transform
        prompt = "请详细分析这个软件服务的并发错误，并用中文提供完整修复、测试和风险。"
        response = await self.client.post(
            "/api/optimize",
            json={
                "prompt": prompt,
                "target_model": "test-model",
                "session_id": session_id,
                "workload_mode": "agentic_coding",
            },
        )

        self.assertEqual(response.status_code, 200)
        decision = response.json()
        self.assertEqual(decision["status"], "bypassed")
        self.assertEqual(decision["fallback_reason"], "provider_unavailable")
        self.assertTrue(decision["effective_settings"]["output_optimization"])
        self.assertFalse(decision["should_auto_run"])
        _, selected_prompt = select_pending_prompt(
            self.runtime,
            decision_id=decision["decision_id"],
            selection="original",
        )
        self.assertEqual(selected_prompt, prompt)

    async def test_wrong_language_candidate_is_visible_but_cannot_be_approved(self):
        self.runtime.provider.candidate = "分析并发错误；中文回答，包含修复、测试和风险。"
        response = await self.client.post(
            "/api/optimize",
            json={
                "prompt": "请详细分析这个软件服务的并发错误，并用中文提供完整修复、测试和风险。",
                "target_model": "test-model",
                "workload_mode": "agentic_coding",
            },
        )

        self.assertEqual(response.status_code, 200)
        decision = response.json()
        self.assertEqual(decision["status"], "rejected")
        self.assertEqual(
            decision["fallback_reason"], "wrong_candidate_language"
        )
        self.assertIsNone(decision["candidate_prompt"])
        self.assertEqual(
            decision["candidate_language"]["detected_language"], "zh"
        )
        self.assertFalse(decision["candidate_language"]["reliable"])
        self.assertEqual(self.runtime.provider.verify_calls, 0)

        approval = await self.client.post(
            "/api/chat",
            json={
                "decision_id": decision["decision_id"],
                "selection": "candidate",
            },
        )
        self.assertEqual(approval.status_code, 409)
        self.assertIn("no verified optimization candidate", approval.json()["detail"])


if __name__ == "__main__":
    unittest.main()
