"""Offline language assessment for transformed prompt candidates."""

from __future__ import annotations

import re
import time
from importlib.metadata import PackageNotFoundError, version

from lingua import Language, LanguageDetectorBuilder

from slashtoken.core.models import CandidateLanguageAssessment


_LANGUAGE_CODES = {
    Language.ENGLISH: "en",
    Language.CHINESE: "zh",
    Language.ARABIC: "ar",
    Language.TURKISH: "tr",
}


class LinguaCandidateLanguageDetector:
    """Require reliably detected English among the MVP's four route languages."""

    def __init__(
        self, *, minimum_confidence_margin: float = 0.15, minimum_letters: int = 12
    ) -> None:
        if not 0 <= minimum_confidence_margin < 1:
            raise ValueError("minimum_confidence_margin must be between 0 and 1.")
        if minimum_letters < 1:
            raise ValueError("minimum_letters must be positive.")
        self.minimum_confidence_margin = minimum_confidence_margin
        self.minimum_letters = minimum_letters
        self._detector = (
            LanguageDetectorBuilder.from_languages(
                Language.ENGLISH,
                Language.CHINESE,
                Language.ARABIC,
                Language.TURKISH,
            )
            .with_minimum_relative_distance(minimum_confidence_margin)
            .build()
        )
        try:
            package_version = version("lingua-language-detector")
        except PackageNotFoundError:
            package_version = "unknown"
        self.name = (
            f"lingua-language-detector:{package_version};"
            f"margin={minimum_confidence_margin};minimum_letters={minimum_letters}"
        )

    def assess_english(self, text: str) -> CandidateLanguageAssessment:
        sample = text.strip()
        started = time.perf_counter()
        detected = self._detector.detect_language_of(sample) if sample else None
        confidence_values = (
            self._detector.compute_language_confidence_values(sample) if sample else []
        )
        latency_ms = (time.perf_counter() - started) * 1000
        confidence_by_language = {
            item.language: float(item.value) for item in confidence_values
        }
        detected_code = _LANGUAGE_CODES.get(detected) if detected is not None else None
        confidence = confidence_by_language.get(detected, 0.0) if detected else 0.0
        letter_count = len(re.findall(r"[^\W\d_]", sample, re.UNICODE))
        return CandidateLanguageAssessment(
            expected_language="en",
            detected_language=detected_code,
            confidence=confidence,
            reliable=(
                detected == Language.ENGLISH and letter_count >= self.minimum_letters
            ),
            detector=self.name,
            latency_ms=latency_ms,
        )
