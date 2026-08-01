"""Local protected-span extraction and deterministic preservation checks."""

from __future__ import annotations

import re
from collections.abc import Iterable

from slashtoken.core.models import ProtectedSpan


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code_block", re.compile(r"```[\s\S]*?```")),
    ("url", re.compile(r"https?://[^\s<>]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("inline_code", re.compile(r"`[^`\n]+`")),
    ("quotation", re.compile(r"[\"“”‘’'«»][^\n\"“”‘’'«»]{2,}[\"“”‘’'«»]")),
    (
        "number",
        re.compile(
            r"(?<!\w)(?:[$€£¥₹₺]\s*)?-?\d[\d,.:/%-]*(?:\s*(?:USD|EUR|GBP|CNY|TRY|%))?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ("identifier", re.compile(r"\b(?=[A-Z0-9_-]{4,}\b)(?=.*[A-Z])(?=.*\d)[A-Z0-9_-]+\b")),
)


def extract_protected_spans(text: str) -> tuple[ProtectedSpan, ...]:
    """Return non-overlapping spans whose exact values must survive transformation."""
    candidates: list[ProtectedSpan] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            candidates.append(
                ProtectedSpan(kind=kind, value=match.group(0), start=match.start(), end=match.end())
            )

    candidates.sort(key=lambda span: (span.start, -(span.end - span.start)))
    selected: list[ProtectedSpan] = []
    for candidate in candidates:
        if any(candidate.start < item.end and item.start < candidate.end for item in selected):
            continue
        selected.append(candidate)
    return tuple(selected)


def missing_protected_spans(
    candidate: str, protected_spans: Iterable[ProtectedSpan]
) -> tuple[ProtectedSpan, ...]:
    """Return exact protected values that disappeared from a candidate."""
    return tuple(span for span in protected_spans if span.value not in candidate)

