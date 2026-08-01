"""Validated SlashToken setting values."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from slashtoken.core.models import ApprovalPolicy, ResponseLanguage, WorkloadMode


@dataclass(frozen=True, slots=True)
class SlashTokenSettings:
    language_optimization: bool = True
    output_optimization: bool = False
    workload_mode: WorkloadMode = WorkloadMode.AGENTIC_CODING
    approval_policy: ApprovalPolicy = ApprovalPolicy.PREVIEW_EACH
    response_language: ResponseLanguage = ResponseLanguage.PRESERVE_SOURCE

    @classmethod
    def from_mapping(
        cls, values: dict[str, Any], *, base: SlashTokenSettings | None = None
    ) -> SlashTokenSettings:
        current = base or cls()
        allowed = {
            "language_optimization",
            "output_optimization",
            "workload_mode",
            "approval_policy",
            "response_language",
        }
        unknown = set(values) - allowed
        if unknown:
            raise ValueError(f"Unknown SlashToken settings: {', '.join(sorted(unknown))}")
        updates: dict[str, Any] = {}
        if "language_optimization" in values:
            updates["language_optimization"] = _required_bool(
                values["language_optimization"], "language_optimization"
            )
        if "output_optimization" in values:
            updates["output_optimization"] = _required_bool(
                values["output_optimization"], "output_optimization"
            )
        if "workload_mode" in values:
            updates["workload_mode"] = WorkloadMode(values["workload_mode"])
        if "approval_policy" in values:
            updates["approval_policy"] = ApprovalPolicy(values["approval_policy"])
        if "response_language" in values:
            updates["response_language"] = ResponseLanguage(values["response_language"])
        return replace(current, **updates)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["workload_mode"] = self.workload_mode.value
        payload["approval_policy"] = self.approval_policy.value
        payload["response_language"] = self.response_language.value
        return payload


def _required_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean.")
    return value

