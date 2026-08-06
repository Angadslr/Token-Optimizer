from __future__ import annotations

import unittest

from slashtoken.core.models import ProtectedSpan
from slashtoken.core.protection import (
    ProtectedPlaceholderError,
    extract_protected_spans,
    missing_protected_spans,
    prioritize_protected_spans,
    restore_protected_spans,
    shield_protected_spans,
    summarize_placeholder_failure,
)
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

    def test_extracts_paired_multilingual_quotations_without_matching_apostrophes(self):
        prompt = "请保留「每月配额 5000」和『错误代码 A-1234』。 Don't alter the user's note."
        values = {span.value for span in extract_protected_spans(prompt)}

        self.assertIn("「每月配额 5000」", values)
        self.assertIn("『错误代码 A-1234』", values)
        self.assertNotIn("'t alter the user'", values)

    def test_missing_check_preserves_duplicate_occurrence_counts(self):
        prompt = "限制 5000，每月配额仍为 5000，警告阈值也是 5000。"
        spans = extract_protected_spans(prompt)

        missing = missing_protected_spans("Keep 5000 once.", spans)

        self.assertEqual(len(missing), 2)
        self.assertTrue(all(span.value == "5000" for span in missing))

    def test_shielding_removes_values_and_restores_them_exactly(self):
        prompt = '请修复 ERR-2048，并保留「每月配额 5000」。'
        spans = extract_protected_spans(prompt)
        shielded = shield_protected_spans(prompt, spans)

        self.assertNotIn("ERR-2048", shielded.text)
        self.assertNotIn("「每月配额 5000」", shielded.text)
        candidate = (
            f"Fix {shielded.bindings[0].placeholder} and preserve "
            f"{shielded.bindings[1].placeholder}. Reply in Chinese."
        )
        restored = restore_protected_spans(candidate, shielded)

        self.assertIn("ERR-2048", restored)
        self.assertIn("「每月配额 5000」", restored)

    def test_restoration_rejects_missing_duplicate_and_reordered_placeholders(self):
        prompt = "请比较 100 和 200。"
        shielded = shield_protected_spans(prompt, extract_protected_spans(prompt))
        first, second = (binding.placeholder for binding in shielded.bindings)

        invalid_candidates = (
            f"Compare {first}.",
            f"Compare {first}, {first}, and {second}.",
            f"Compare {second} and {first}.",
        )
        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ProtectedPlaceholderError):
                    restore_protected_spans(candidate, shielded)

    def test_prioritize_keeps_all_spans_below_soft_limit(self):
        spans = (
            ProtectedSpan(kind="quotation", value='"a"', start=0, end=3),
            ProtectedSpan(kind="inline_code", value="`b`", start=4, end=7),
            ProtectedSpan(kind="url", value="https://x.example", start=8, end=25),
        )

        self.assertEqual(prioritize_protected_spans(spans, soft_limit=40), spans)

    def test_prioritize_drops_low_value_kinds_above_soft_limit(self):
        spans = (
            ProtectedSpan(kind="quotation", value='"a"', start=0, end=3),
            ProtectedSpan(kind="inline_code", value="`b`", start=4, end=7),
            ProtectedSpan(kind="url", value="https://x.example", start=8, end=25),
            ProtectedSpan(kind="number", value="5000", start=26, end=30),
        )

        kept = prioritize_protected_spans(spans, soft_limit=2)

        kept_kinds = {span.kind for span in kept}
        self.assertEqual(kept_kinds, {"url", "number"})
        self.assertNotIn("quotation", kept_kinds)
        self.assertNotIn("inline_code", kept_kinds)

    def test_prioritize_soft_limit_zero_disables_trimming(self):
        spans = (
            ProtectedSpan(kind="quotation", value='"a"', start=0, end=3),
            ProtectedSpan(kind="inline_code", value="`b`", start=4, end=7),
        )

        self.assertEqual(prioritize_protected_spans(spans, soft_limit=0), spans)

    def test_summary_reports_privacy_safe_mismatch_counts(self):
        prompt = "请比较 100、200 和 `token_id`。"
        shielded = shield_protected_spans(prompt, extract_protected_spans(prompt))
        first, second, third = (b.placeholder for b in shielded.bindings)

        candidate = f"Compare {second} and {second}."
        summary = summarize_placeholder_failure(candidate, shielded)

        self.assertIn(f"expected {len(shielded.bindings)}", summary)
        self.assertIn("missing 2", summary)
        self.assertIn("duplicated 1", summary)
        for binding in shielded.bindings:
            self.assertNotIn(binding.placeholder, summary)
            self.assertNotIn(binding.original.value, summary)

    def test_summary_reports_reordered_placeholders(self):
        prompt = "请比较 100 和 200。"
        shielded = shield_protected_spans(prompt, extract_protected_spans(prompt))
        first, second = (b.placeholder for b in shielded.bindings)

        summary = summarize_placeholder_failure(f"Compare {second} then {first}.", shielded)

        self.assertIn("reordered", summary)


if __name__ == "__main__":
    unittest.main()
