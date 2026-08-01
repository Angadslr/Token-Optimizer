from __future__ import annotations

import unittest

from slashtoken.core.protection import extract_protected_spans, missing_protected_spans
from slashtoken.core.risk import classify_risk, detect_language


class RiskAndProtectionTests(unittest.TestCase):
    def test_detects_supported_languages(self):
        self.assertEqual(detect_language("请分析这个错误"), "zh")
        self.assertEqual(detect_language("حلّل هذا الخطأ"), "ar")
        self.assertEqual(detect_language("Lütfen bu yazılım hatasını analiz et"), "tr")

    def test_distinguishes_english_and_unknown(self):
        self.assertEqual(detect_language("Analyze this failure"), "en")
        self.assertEqual(detect_language("12345"), "und")

    def test_high_stakes_terms_are_conservative(self):
        assessment = classify_risk("请给我这个症状的诊断和药物剂量")
        self.assertTrue(assessment.high_stakes)
        self.assertIn("medical", assessment.categories)

    def test_extracts_and_checks_exact_protected_values(self):
        prompt = 'Use `process_batch`, ERR-2048, 30 seconds, and https://example.com. Keep "do not deploy".'
        spans = extract_protected_spans(prompt)
        values = {span.value for span in spans}
        self.assertIn("`process_batch`", values)
        self.assertIn("ERR-2048", values)
        self.assertIn("https://example.com.", values)
        candidate = "Use `process_batch`, ERR-2048, 30 seconds and https://example.com. Keep do not deploy."
        missing = missing_protected_spans(candidate, spans)
        self.assertTrue(any(span.kind == "quotation" for span in missing))


if __name__ == "__main__":
    unittest.main()

