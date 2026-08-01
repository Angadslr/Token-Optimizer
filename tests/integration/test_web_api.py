from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None

from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.runtime import DecisionCache, SlashTokenRuntime
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
        self.assertFalse(decision.json()["should_auto_run"])


if __name__ == "__main__":
    unittest.main()
