from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from slashtoken.runtime import _optional_positive_int_or_disabled, _positive_float


class RuntimeConfigurationTests(unittest.TestCase):
    def test_positive_float_uses_default_when_unset_or_blank(self):
        for value in (None, "", "   "):
            with self.subTest(value=value):
                environment = {} if value is None else {"TEST_TIMEOUT": value}
                with patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(
                        _positive_float("TEST_TIMEOUT", 300.0), 300.0
                    )

    def test_positive_float_parses_configured_value(self):
        with patch.dict(os.environ, {"TEST_TIMEOUT": "600"}, clear=True):
            self.assertEqual(_positive_float("TEST_TIMEOUT", 300.0), 600.0)

    def test_positive_float_rejects_nonpositive_and_invalid(self):
        for value in ("0", "-5", "invalid"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TEST_TIMEOUT": value}, clear=True):
                    with self.assertRaises(ValueError):
                        _positive_float("TEST_TIMEOUT", 300.0)

    def test_transformation_limit_switch_accepts_disabled_values(self):
        for value in (None, "", "0", "none", "off", "unlimited"):
            with self.subTest(value=value):
                environment = {} if value is None else {"TEST_LIMIT": value}
                with patch.dict(os.environ, environment, clear=True):
                    self.assertIsNone(
                        _optional_positive_int_or_disabled("TEST_LIMIT")
                    )

    def test_transformation_limit_switch_accepts_positive_integer(self):
        with patch.dict(os.environ, {"TEST_LIMIT": "6000"}, clear=True):
            self.assertEqual(
                _optional_positive_int_or_disabled("TEST_LIMIT"), 6000
            )

    def test_transformation_limit_switch_rejects_invalid_values(self):
        for value in ("-1", "invalid"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {"TEST_LIMIT": value}, clear=True):
                    with self.assertRaises((ValueError, TypeError)):
                        _optional_positive_int_or_disabled("TEST_LIMIT")


if __name__ == "__main__":
    unittest.main()
