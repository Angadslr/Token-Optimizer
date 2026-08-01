from __future__ import annotations

import unittest

from slashtoken.codex.app_server import build_thread_overrides, build_turn_params
from slashtoken.core.models import WorkloadMode


class CodexContractTests(unittest.TestCase):
    def test_turn_contains_exactly_one_selected_prompt(self):
        params = build_turn_params(
            thread_id="thr_123", selected_prompt="approved candidate", model="model-x"
        )
        self.assertEqual(
            params["input"], [{"type": "text", "text": "approved candidate"}]
        )
        self.assertEqual(params["model"], "model-x")
        self.assertNotIn("original", params)
        self.assertNotIn("candidate", params)

    def test_output_optimization_is_thread_scoped(self):
        overrides = build_thread_overrides(
            output_optimization=True,
            workload_mode=WorkloadMode.AGENTIC_CODING,
        )
        self.assertEqual(overrides["config"]["model_verbosity"], "low")
        self.assertIn("tests", overrides["developerInstructions"])
        self.assertEqual(
            build_thread_overrides(
                output_optimization=False,
                workload_mode=WorkloadMode.AGENTIC_CODING,
            ),
            {},
        )

    def test_chatbot_output_profile_preserves_requested_depth(self):
        overrides = build_thread_overrides(
            output_optimization=True,
            workload_mode=WorkloadMode.CHATBOT,
        )
        self.assertEqual(overrides["config"]["model_verbosity"], "low")
        self.assertIn("requested detail", overrides["developerInstructions"])
        self.assertNotIn("max_output", str(overrides))


if __name__ == "__main__":
    unittest.main()
