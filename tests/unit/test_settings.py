from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from slashtoken.settings.resolver import SettingsResolver
from slashtoken.storage.database import SlashTokenDatabase
from slashtoken.storage.repositories import SlashTokenRepository


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        repository = SlashTokenRepository(
            SlashTokenDatabase(Path(self.temp.name) / "settings.sqlite3")
        )
        self.resolver = SettingsResolver(repository)

    def tearDown(self):
        self.temp.cleanup()

    def test_session_overrides_project_and_user(self):
        project = str(Path(self.temp.name) / "project")
        self.resolver.update(
            scope="user", values={"language_optimization": False}
        )
        self.resolver.update(
            scope="project",
            project_path=project,
            values={"language_optimization": True, "workload_mode": "chatbot"},
        )
        self.resolver.update(
            scope="session",
            session_id="s1",
            values={"language_optimization": False, "workload_mode": "agentic_coding"},
        )
        effective = self.resolver.resolve(project_path=project, session_id="s1")
        self.assertFalse(effective.language_optimization)
        self.assertEqual(effective.workload_mode.value, "agentic_coding")

    def test_user_scope_cannot_authorize_auto_submission(self):
        with self.assertRaisesRegex(ValueError, "cannot authorize"):
            self.resolver.update(
                scope="user", values={"approval_policy": "auto_verified"}
            )

    def test_project_consent_is_local_and_resolvable(self):
        project = str(Path(self.temp.name) / "project")
        settings = self.resolver.update(
            scope="project",
            project_path=project,
            values={"approval_policy": "auto_verified"},
        )
        self.assertEqual(settings.approval_policy.value, "auto_verified")

    def test_project_stores_only_explicit_overrides(self):
        project = str(Path(self.temp.name) / "project")
        self.resolver.update(
            scope="project",
            project_path=project,
            values={"output_optimization": True},
        )
        self.resolver.update(
            scope="user", values={"language_optimization": False}
        )
        effective = self.resolver.resolve(project_path=project)
        self.assertTrue(effective.output_optimization)
        self.assertFalse(effective.language_optimization)


if __name__ == "__main__":
    unittest.main()
