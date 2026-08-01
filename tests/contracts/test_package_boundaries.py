from __future__ import annotations

import unittest
from pathlib import Path


class PackageBoundaryTests(unittest.TestCase):
    def test_production_never_imports_experiments(self):
        root = Path(__file__).resolve().parents[2] / "src" / "slashtoken"
        violations = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "experiments." in text or "from experiments" in text:
                violations.append(str(path))
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

