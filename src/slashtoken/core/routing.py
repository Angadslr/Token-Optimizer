"""Threshold registry and route decision helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RoutingThreshold:
    language: str
    model: str
    minimum_tokens_saved: int
    minimum_percent_saved: float
    calibrated: bool
    version: str

    def __post_init__(self) -> None:
        if not self.language.strip():
            raise ValueError("Threshold language cannot be empty.")
        if not self.model.strip():
            raise ValueError("Threshold model cannot be empty.")
        if self.minimum_tokens_saved < 0:
            raise ValueError("minimum_tokens_saved cannot be negative.")
        if not 0 <= self.minimum_percent_saved <= 100:
            raise ValueError("minimum_percent_saved must be between 0 and 100.")
        if not self.version.strip():
            raise ValueError("Threshold version cannot be empty.")

    def qualifies(self, original_tokens: int, candidate_tokens: int) -> bool:
        saved = original_tokens - candidate_tokens
        percent = (saved / original_tokens * 100) if original_tokens else 0.0
        return saved >= self.minimum_tokens_saved and percent >= self.minimum_percent_saved


class ThresholdRegistry:
    """Versioned thresholds keyed by language and target model."""

    def __init__(self, thresholds: tuple[RoutingThreshold, ...] = ()) -> None:
        indexed: dict[tuple[str, str], RoutingThreshold] = {}
        for item in thresholds:
            key = (item.language, item.model)
            if key in indexed:
                raise ValueError(
                    f"Duplicate threshold for language={item.language!r}, model={item.model!r}."
                )
            indexed[key] = item
        self._thresholds = indexed

    @classmethod
    def from_json_file(cls, path: str | Path) -> ThresholdRegistry:
        """Load versioned benchmark thresholds from an explicit local file."""
        payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("thresholds"), list):
            raise ValueError("Threshold file must contain a 'thresholds' array.")
        thresholds = tuple(cls._parse_threshold(item) for item in payload["thresholds"])
        return cls(thresholds)

    @staticmethod
    def _parse_threshold(item: Any) -> RoutingThreshold:
        if not isinstance(item, dict):
            raise ValueError("Each threshold must be a JSON object.")
        expected = {
            "language",
            "model",
            "minimum_tokens_saved",
            "minimum_percent_saved",
            "calibrated",
            "version",
        }
        unknown = set(item) - expected
        missing = expected - set(item)
        if unknown or missing:
            details = []
            if missing:
                details.append(f"missing: {', '.join(sorted(missing))}")
            if unknown:
                details.append(f"unknown: {', '.join(sorted(unknown))}")
            raise ValueError(f"Invalid threshold fields ({'; '.join(details)}).")
        if isinstance(item["minimum_tokens_saved"], bool) or not isinstance(
            item["minimum_tokens_saved"], int
        ):
            raise ValueError("minimum_tokens_saved must be an integer.")
        if isinstance(item["minimum_percent_saved"], bool) or not isinstance(
            item["minimum_percent_saved"], (int, float)
        ):
            raise ValueError("minimum_percent_saved must be numeric.")
        if not isinstance(item["calibrated"], bool):
            raise ValueError("calibrated must be a boolean.")
        return RoutingThreshold(
            language=str(item["language"]),
            model=str(item["model"]),
            minimum_tokens_saved=item["minimum_tokens_saved"],
            minimum_percent_saved=float(item["minimum_percent_saved"]),
            calibrated=item["calibrated"],
            version=str(item["version"]),
        )

    def get(self, language: str, model: str) -> RoutingThreshold:
        exact = self._thresholds.get((language, model))
        if exact:
            return exact
        wildcard = self._thresholds.get((language, "*"))
        if wildcard:
            return wildcard
        return RoutingThreshold(
            language=language,
            model=model,
            minimum_tokens_saved=1,
            minimum_percent_saved=0.0,
            calibrated=False,
            version="uncalibrated-v1",
        )
