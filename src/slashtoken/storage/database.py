"""SQLite lifecycle and schema management."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS settings (
    scope TEXT NOT NULL CHECK(scope IN ('user', 'project')),
    scope_key TEXT NOT NULL,
    values_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scope, scope_key)
);

CREATE TABLE IF NOT EXISTS routing_decisions (
    decision_id TEXT PRIMARY KEY,
    prompt_hash TEXT NOT NULL,
    project_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source_language TEXT NOT NULL,
    target_model TEXT NOT NULL,
    workload_mode TEXT NOT NULL,
    status TEXT NOT NULL,
    fallback_reason TEXT,
    original_tokens INTEGER NOT NULL,
    candidate_tokens INTEGER,
    token_savings INTEGER NOT NULL,
    tokenizer TEXT NOT NULL,
    optimizer_cost_usd REAL NOT NULL,
    optimizer_cost_available INTEGER NOT NULL,
    latency_ms REAL NOT NULL,
    verification_valid INTEGER,
    protected_span_count INTEGER NOT NULL,
    auto_run_eligible INTEGER NOT NULL,
    threshold_version TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (decision_id) REFERENCES routing_decisions(decision_id)
);

CREATE TABLE IF NOT EXISTS codex_runs (
    run_id TEXT PRIMARY KEY,
    decision_id TEXT NOT NULL,
    thread_id TEXT,
    turn_id TEXT,
    model TEXT NOT NULL,
    project_hash TEXT,
    status TEXT NOT NULL CHECK(status IN (
        'starting', 'running', 'waiting_for_approval',
        'completed', 'failed', 'interrupted'
    )),
    failure_code TEXT,
    usage_json TEXT NOT NULL DEFAULT '{}',
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (decision_id) REFERENCES routing_decisions(decision_id)
);

CREATE INDEX IF NOT EXISTS idx_codex_runs_thread_updated
ON codex_runs(thread_id, updated_at DESC);
"""


def default_database_path() -> Path:
    override = os.environ.get("SLASHTOKEN_DATABASE_PATH")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.uname().sysname == "Darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "SlashToken" / "slashtoken.sqlite3"


class SlashTokenDatabase:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else default_database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self.connect()
        try:
            connection.executescript(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(routing_decisions)")
            }
            if "optimizer_cost_available" not in columns:
                connection.execute(
                    """
                    ALTER TABLE routing_decisions
                    ADD COLUMN optimizer_cost_available INTEGER NOT NULL DEFAULT 0
                    """
                )
            connection.commit()
        finally:
            connection.close()
