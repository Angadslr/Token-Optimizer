"""Local protected-span extraction and deterministic preservation checks."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

from slashtoken.core.models import ProtectedSpan


_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("code_block", re.compile(r"```[\s\S]*?```")),
    ("url", re.compile(r"https?://[^\s<>]+")),
    ("email", re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("inline_code", re.compile(r"`[^`\n]+`")),
    ("quotation", re.compile(r'"[^"\n]{2,}"')),
    ("quotation", re.compile(r"“[^”\n]{2,}”")),
    ("quotation", re.compile(r"‘[^’\n]{2,}’")),
    ("quotation", re.compile(r"«[^»\n]{2,}»")),
    ("quotation", re.compile(r"「[^」\n]{2,}」")),
    ("quotation", re.compile(r"『[^』\n]{2,}』")),
    ("quotation", re.compile(r"《[^》\n]{2,}》")),
    ("quotation", re.compile(r"(?<!\w)'[^'\n]{2,}'(?!\w)")),
    (
        "number",
        re.compile(
            r"(?<!\w)(?:[$€£¥₹₺]\s*)?-?\d[\d,.:/%-]*(?:\s*(?:USD|EUR|GBP|CNY|TRY|%))?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    ("identifier", re.compile(r"\b(?=[A-Z0-9_-]{4,}\b)(?=.*[A-Z])(?=.*\d)[A-Z0-9_-]+\b")),
)

# High-density prompts can produce so many placeholders that hosted transformers
# reliably drop or reorder some of them. When the span count crosses a soft limit,
# these lower-value kinds are left unshielded so the high-value ones (money, IDs,
# URLs, emails, code fences) still survive intact.
LOW_VALUE_PROTECTED_KINDS = frozenset({"quotation", "inline_code"})


class ProtectedPlaceholderError(ValueError):
    """Raised when a transformer changes the protected-placeholder contract."""


@dataclass(frozen=True, slots=True)
class ProtectedBinding:
    """Map one opaque transformation placeholder back to its exact source span."""

    placeholder: str
    original: ProtectedSpan


@dataclass(frozen=True, slots=True)
class ShieldedPrompt:
    """Prompt text safe for transformation plus deterministic restoration metadata."""

    text: str
    bindings: tuple[ProtectedBinding, ...]
    placeholder_spans: tuple[ProtectedSpan, ...]


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
    """Return protected occurrences not present exactly in a candidate."""
    spans = tuple(protected_spans)
    available = Counter({value: candidate.count(value) for value in {s.value for s in spans}})
    missing: list[ProtectedSpan] = []
    for span in spans:
        if available[span.value] <= 0:
            missing.append(span)
            continue
        available[span.value] -= 1
    return tuple(missing)


def without_protected_values(
    candidate: str, protected_spans: Iterable[ProtectedSpan]
) -> str:
    """Remove the required protected occurrences before language assessment."""
    values = Counter(span.value for span in protected_spans)
    sample = candidate
    for value, count in sorted(values.items(), key=lambda item: len(item[0]), reverse=True):
        sample = sample.replace(value, " ", count)
    return sample


def shield_protected_spans(
    text: str, protected_spans: Iterable[ProtectedSpan]
) -> ShieldedPrompt:
    """Replace protected source content with deterministic, collision-resistant tokens."""
    spans = tuple(sorted(protected_spans, key=lambda span: span.start))
    if not spans:
        return ShieldedPrompt(text=text, bindings=(), placeholder_spans=())

    namespace = sha256(text.encode("utf-8")).hexdigest()[:12].upper()
    while f"__STP_{namespace}_" in text:
        namespace = sha256(namespace.encode("ascii")).hexdigest()[:12].upper()

    parts: list[str] = []
    bindings: list[ProtectedBinding] = []
    placeholder_spans: list[ProtectedSpan] = []
    source_cursor = 0
    shielded_length = 0
    for index, span in enumerate(spans):
        if span.start < source_cursor:
            raise ValueError("Protected spans must not overlap.")
        prefix = text[source_cursor : span.start]
        placeholder = f"__STP_{namespace}_{index:04d}__"
        parts.extend((prefix, placeholder))
        shielded_length += len(prefix)
        placeholder_spans.append(
            ProtectedSpan(
                kind=span.kind,
                value=placeholder,
                start=shielded_length,
                end=shielded_length + len(placeholder),
            )
        )
        shielded_length += len(placeholder)
        bindings.append(ProtectedBinding(placeholder=placeholder, original=span))
        source_cursor = span.end
    parts.append(text[source_cursor:])
    return ShieldedPrompt(
        text="".join(parts),
        bindings=tuple(bindings),
        placeholder_spans=tuple(placeholder_spans),
    )


def restore_protected_spans(candidate: str, shielded: ShieldedPrompt) -> str:
    """Validate the placeholder contract, then restore exact source values."""
    validate_protected_placeholders(candidate, shielded)
    restored = candidate
    for binding in shielded.bindings:
        restored = restored.replace(binding.placeholder, binding.original.value, 1)
    return restored


def validate_protected_placeholders(candidate: str, shielded: ShieldedPrompt) -> None:
    """Require every opaque placeholder exactly once and in source order."""
    positions: list[int] = []
    for binding in shielded.bindings:
        count = candidate.count(binding.placeholder)
        if count != 1:
            raise ProtectedPlaceholderError(
                f"Protected placeholder must occur exactly once; found {count}."
            )
        positions.append(candidate.index(binding.placeholder))
    if positions != sorted(positions):
        raise ProtectedPlaceholderError("Protected placeholders changed order.")


def prioritize_protected_spans(
    spans: Iterable[ProtectedSpan], *, soft_limit: int
) -> tuple[ProtectedSpan, ...]:
    """Drop low-value span kinds once the placeholder count crosses a soft limit.

    Over-protection is a common cause of transform failure: hosted models drop or
    reorder tokens more often as the placeholder set grows. When the count is high
    we keep protecting money, IDs, URLs, emails, and code fences while releasing
    short quotations and inline backtick paths, which are cheap to get slightly
    wrong and expensive to protect. Below the limit, nothing is dropped.
    """
    ordered = tuple(spans)
    if soft_limit <= 0 or len(ordered) <= soft_limit:
        return ordered
    return tuple(span for span in ordered if span.kind not in LOW_VALUE_PROTECTED_KINDS)


def summarize_placeholder_failure(candidate: str, shielded: ShieldedPrompt) -> str:
    """Return a privacy-safe reason string for a placeholder-contract failure.

    Reports only counts and generic span kinds. It never includes placeholder
    tokens, restored values, or any prompt text, so it is safe for receipts.
    """
    total = len(shielded.bindings)
    missing = 0
    duplicated = 0
    positions: list[int] = []
    missing_by_kind: Counter[str] = Counter()
    duplicated_by_kind: Counter[str] = Counter()
    for binding in shielded.bindings:
        count = candidate.count(binding.placeholder)
        if count == 0:
            missing += 1
            missing_by_kind[binding.original.kind] += 1
        elif count > 1:
            duplicated += 1
            duplicated_by_kind[binding.original.kind] += 1
        else:
            positions.append(candidate.index(binding.placeholder))
    reordered = positions != sorted(positions)

    parts = [f"expected {total}"]
    if missing:
        parts.append(f"missing {missing}")
    if duplicated:
        parts.append(f"duplicated {duplicated}")
    if reordered:
        parts.append("reordered")

    kinds: list[str] = []
    for kind, count in sorted(missing_by_kind.items()):
        kinds.append(f"{kind} missing {count}")
    for kind, count in sorted(duplicated_by_kind.items()):
        kinds.append(f"{kind} duplicated {count}")

    summary = ", ".join(parts)
    if kinds:
        summary += f"; {'; '.join(kinds)}"
    return summary
