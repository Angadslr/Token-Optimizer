from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from slashtoken.core.routing import ThresholdRegistry


class ThresholdRegistryTests(unittest.TestCase):
    def test_loads_explicit_versioned_threshold_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(
                json.dumps(
                    {
                        "thresholds": [
                            {
                                "language": "zh",
                                "model": "test-model",
                                "minimum_tokens_saved": 20,
                                "minimum_percent_saved": 12.5,
                                "calibrated": True,
                                "version": "held-out-2026-07-v1",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            threshold = ThresholdRegistry.from_json_file(path).get(
                "zh", "test-model"
            )

            self.assertTrue(threshold.calibrated)
            self.assertEqual(threshold.minimum_tokens_saved, 20)
            self.assertEqual(threshold.version, "held-out-2026-07-v1")

    def test_rejects_unknown_threshold_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text(
                json.dumps(
                    {
                        "thresholds": [
                            {
                                "language": "zh",
                                "model": "test-model",
                                "minimum_tokens_saved": 20,
                                "minimum_percent_saved": 10,
                                "calibrated": True,
                                "version": "v1",
                                "unsafe_override": True,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "unknown"):
                ThresholdRegistry.from_json_file(path)


if __name__ == "__main__":
    unittest.main()
