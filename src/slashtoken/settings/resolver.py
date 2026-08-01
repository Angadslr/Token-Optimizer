"""Resolve user, local-project, and in-memory session settings."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from slashtoken.core.models import ApprovalPolicy
from slashtoken.settings.schema import SlashTokenSettings


class SettingsRepository(Protocol):
    def get_settings(self, scope: str, scope_key: str) -> dict[str, Any]: ...

    def put_settings(self, scope: str, scope_key: str, values: dict[str, Any]) -> None: ...


class SettingsResolver:
    """Apply session > project > user settings without trusting repository files."""

    def __init__(self, repository: SettingsRepository) -> None:
        self.repository = repository
        self._session_values: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    @staticmethod
    def project_key(project_path: str | None) -> str | None:
        if not project_path:
            return None
        return str(Path(project_path).expanduser().resolve())

    def resolve(
        self, *, project_path: str | None = None, session_id: str | None = None
    ) -> SlashTokenSettings:
        settings = SlashTokenSettings()
        user_values = self.repository.get_settings("user", "default")
        settings = SlashTokenSettings.from_mapping(user_values, base=settings)
        project_key = self.project_key(project_path)
        if project_key:
            project_values = self.repository.get_settings("project", project_key)
            settings = SlashTokenSettings.from_mapping(project_values, base=settings)
        if session_id:
            with self._lock:
                session_values = dict(self._session_values.get(session_id, {}))
            settings = SlashTokenSettings.from_mapping(session_values, base=settings)
        return settings

    def update(
        self,
        *,
        scope: str,
        values: dict[str, Any],
        project_path: str | None = None,
        session_id: str | None = None,
    ) -> SlashTokenSettings:
        if scope not in {"user", "project", "session"}:
            raise ValueError("scope must be user, project, or session.")
        if scope == "user" and values.get("approval_policy") == ApprovalPolicy.AUTO_VERIFIED.value:
            raise ValueError("User-wide settings cannot authorize automatic submission.")

        if scope == "user":
            key = "default"
            current = self.repository.get_settings(scope, key)
            merged = SlashTokenSettings.from_mapping(values, base=SlashTokenSettings.from_mapping(current))
            persisted = merged.to_dict()
            if persisted["approval_policy"] == ApprovalPolicy.AUTO_VERIFIED.value:
                persisted["approval_policy"] = ApprovalPolicy.PREVIEW_EACH.value
            self.repository.put_settings(scope, key, persisted)
        elif scope == "project":
            key = self.project_key(project_path)
            if not key:
                raise ValueError("project_path is required for project settings.")
            current_overrides = self.repository.get_settings(scope, key)
            requested_overrides = {**current_overrides, **values}
            validated = SlashTokenSettings.from_mapping(
                requested_overrides, base=self.resolve()
            ).to_dict()
            self.repository.put_settings(
                scope,
                key,
                {name: validated[name] for name in requested_overrides},
            )
        else:
            if not session_id:
                raise ValueError("session_id is required for session settings.")
            with self._lock:
                current = dict(self._session_values.get(session_id, {}))
                current.update(values)
                SlashTokenSettings.from_mapping(current)
                self._session_values[session_id] = current
        return self.resolve(project_path=project_path, session_id=session_id)

    def clear_session(self, session_id: str) -> None:
        with self._lock:
            self._session_values.pop(session_id, None)
