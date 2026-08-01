from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from slashtoken.core.pipeline import OptimizationPipeline
from slashtoken.mcp.server import register_tools
from slashtoken.runtime import DecisionCache, SlashTokenRuntime
from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository
from tests.helpers import FakeProvider, MultilingualTokenCounter


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def decorator(function):
            self.tools[function.__name__] = function
            return function
        return decorator


class MCPContractTests(unittest.TestCase):
    def test_expected_tools_are_registered(self):
        mcp = FakeMCP()
        register_tools(mcp, runtime=object())
        self.assertEqual(
            set(mcp.tools),
            {
                "analyze_prompt",
                "optimize_prompt",
                "run_chat",
                "settings_get",
                "settings_update",
                "usage_summary",
            },
        )

    def test_optimize_preview_is_required_before_single_route_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            database = SlashTokenDatabase(Path(directory) / "mcp.sqlite3")
            repository = SlashTokenRepository(database)
            provider = FakeProvider(
                candidate="Analyze concurrency. Reply Chinese with complete fix and tests."
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
            mcp = FakeMCP()
            register_tools(mcp, runtime)
            prompt = "请分析这个服务中的并发问题，并用中文提供完整修复和测试。"

            with self.assertRaises(KeyError):
                mcp.tools["run_chat"]("missing-decision")

            decision = mcp.tools["optimize_prompt"](prompt, "test-model")
            result = mcp.tools["run_chat"](decision["decision_id"], "candidate")

            self.assertEqual(result["selected_route"], "candidate")
            self.assertEqual(provider.chat_calls, 1)
            self.assertEqual(provider.last_chat_prompt, decision["candidate_prompt"])
            self.assertNotEqual(provider.last_chat_prompt, prompt)


if __name__ == "__main__":
    unittest.main()
