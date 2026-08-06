from __future__ import annotations

import unittest

try:
    from slashtoken.providers.lingua_language import LinguaCandidateLanguageDetector
except ImportError:
    LinguaCandidateLanguageDetector = None


@unittest.skipUnless(
    LinguaCandidateLanguageDetector is not None,
    "lingua-language-detector is not installed",
)
class LinguaCandidateLanguageDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = LinguaCandidateLanguageDetector()

    def test_accepts_reliable_compact_english(self):
        assessment = self.detector.assess_english(
            "Analyze the concurrency defect. Provide a complete fix and tests. "
            "Respond in Chinese."
        )

        self.assertTrue(assessment.reliable)
        self.assertEqual(assessment.detected_language, "en")
        self.assertGreater(assessment.confidence, 0.5)

    def test_rejects_supported_source_languages_and_ambiguous_text(self):
        examples = (
            ("分析并发错误并用中文提供完整修复。", "zh"),
            ("حلل خطأ التزامن وقدم إصلاحا كاملا.", "ar"),
            ("Eşzamanlılık hatasını analiz et ve eksiksiz düzeltme sun.", "tr"),
            ("qzx", None),
        )

        for text, expected in examples:
            with self.subTest(expected=expected):
                assessment = self.detector.assess_english(text)
                self.assertFalse(assessment.reliable)
                self.assertEqual(assessment.detected_language, expected)


if __name__ == "__main__":
    unittest.main()
