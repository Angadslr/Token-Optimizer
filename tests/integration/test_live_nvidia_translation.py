from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(
    os.environ.get("SLASHTOKEN_RUN_LIVE_TESTS") == "1",
    "set SLASHTOKEN_RUN_LIVE_TESTS=1 to spend NVIDIA API credits",
)
class LiveNvidiaTranslationTests(unittest.TestCase):
    def test_gui_optimization_path_returns_verified_english_candidate(self):
        try:
            from fastapi.testclient import TestClient
        except ImportError as error:
            self.skipTest(f"FastAPI test dependencies are unavailable: {error}")

        from slashtoken.runtime import build_runtime
        from slashtoken.web.app import create_app

        fixture = json.loads(
            Path("benchmarks/fixtures/prompts.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        with tempfile.TemporaryDirectory() as directory:
            runtime = build_runtime(
                database_path=str(Path(directory) / "live-translation.sqlite3")
            )
            with TestClient(create_app(runtime)) as client:
                response = client.post(
                    "/api/optimize",
                    json={
                        "prompt": fixture["prompt"],
                        "target_model": "gpt-4o",
                        "workload_mode": fixture["workload_mode"],
                    },
                )

        self.assertEqual(response.status_code, 200, response.text)
        decision = response.json()
        self.assertEqual(decision["status"], "candidate", decision)
        candidate = decision["candidate_prompt"]
        self.assertEqual(decision["candidate_language"]["detected_language"], "en")
        self.assertTrue(decision["candidate_language"]["reliable"])
        self.assertIn("process_batch", candidate)
        self.assertIn("ERR-2048", candidate)
        self.assertIn("30", candidate)
        self.assertIn("chinese", candidate.casefold())
        self.assertNotIn("__STP_", candidate)
        self.assertIsNone(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", candidate))
        self.assertTrue(decision["verification"]["is_prompt_not_answer"])
        self.assertTrue(decision["verification"]["preserves_requirements"])
        self.assertGreater(decision["token_savings"], 0)
        self.assertEqual(
            [stage["stage"] for stage in decision["stage_usage"]],
            ["prompt_transformation", "semantic_verification"],
        )
        print(
            json.dumps(
                {
                    "candidate_prompt": candidate,
                    "status": decision["status"],
                    "candidate_language": decision["candidate_language"],
                    "original_tokens": decision["original_tokens"],
                    "candidate_tokens": decision["candidate_tokens"],
                    "token_savings": decision["token_savings"],
                    "stage_usage": decision["stage_usage"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    unittest.main()
