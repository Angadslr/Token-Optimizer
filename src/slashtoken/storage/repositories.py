"""Sanitized settings and metrics repositories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from slashtoken.core.models import OptimizationRequest, RoutingDecision
from slashtoken.storage.database import SlashTokenDatabase


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class SlashTokenRepository:
    def __init__(self, database: SlashTokenDatabase) -> None:
        self.database = database

    def get_settings(self, scope: str, scope_key: str) -> dict[str, Any]:
        with self.database.session() as connection:
            row = connection.execute(
                "SELECT values_json FROM settings WHERE scope = ? AND scope_key = ?",
                (scope, scope_key),
            ).fetchone()
        if row is None:
            return {}
        payload = json.loads(row["values_json"])
        if not isinstance(payload, dict):
            raise RuntimeError("Stored SlashToken settings are invalid.")
        return payload

    def put_settings(self, scope: str, scope_key: str, values: dict[str, Any]) -> None:
        serialized = json.dumps(values, sort_keys=True, separators=(",", ":"))
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO settings(scope, scope_key, values_json, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(scope, scope_key) DO UPDATE SET
                    values_json = excluded.values_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (scope, scope_key, serialized),
            )

    def record_decision(
        self, request: OptimizationRequest, decision: RoutingDecision
    ) -> None:
        prompt_hash = _sha256(request.normalized_prompt())
        project_hash = (
            _sha256(str(Path(request.project_path).expanduser().resolve()))
            if request.project_path
            else None
        )
        latency_ms = sum(stage.latency_ms for stage in decision.stage_usage)
        verification_valid = (
            int(decision.verification.valid) if decision.verification is not None else None
        )
        language = decision.candidate_language
        tokenizer = decision.original_tokens.tokenizer
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO routing_decisions(
                    decision_id, prompt_hash, project_hash, source_language,
                    target_model, workload_mode, status, fallback_reason,
                    original_tokens, candidate_tokens, token_savings, tokenizer,
                    optimizer_cost_usd, latency_ms, verification_valid,
                    optimizer_cost_available, candidate_language,
                    candidate_language_confidence, candidate_language_reliable,
                    candidate_language_detector, candidate_language_latency_ms,
                    protected_span_count,
                    auto_run_eligible, threshold_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    prompt_hash,
                    project_hash,
                    decision.source_language,
                    request.target_model,
                    request.workload_mode.value,
                    decision.status.value,
                    decision.fallback_reason.value if decision.fallback_reason else None,
                    decision.original_tokens.tokens,
                    decision.candidate_tokens.tokens if decision.candidate_tokens else None,
                    decision.token_savings,
                    tokenizer,
                    decision.optimizer_cost_usd,
                    latency_ms,
                    verification_valid,
                    int(decision.optimizer_cost_available),
                    language.detected_language if language else None,
                    language.confidence if language else None,
                    int(language.reliable) if language else None,
                    language.detector if language else None,
                    language.latency_ms if language else None,
                    decision.protected_span_count,
                    int(decision.auto_run_eligible),
                    decision.threshold_version,
                ),
            )

    def record_approval(self, decision_id: str, action: str, scope: str | None = None) -> None:
        with self.database.session() as connection:
            connection.execute(
                "INSERT INTO approval_events(decision_id, action, scope) VALUES (?, ?, ?)",
                (decision_id, action, scope),
            )

    def create_codex_run(
        self,
        *,
        run_id: str,
        decision_id: str,
        model: str,
        project_path: str | None,
    ) -> None:
        project_hash = (
            _sha256(str(Path(project_path).expanduser().resolve()))
            if project_path
            else None
        )
        with self.database.session() as connection:
            connection.execute(
                """
                INSERT INTO codex_runs(
                    run_id, decision_id, model, project_hash, status
                ) VALUES (?, ?, ?, ?, 'starting')
                """,
                (run_id, decision_id, model, project_hash),
            )

    def update_codex_run_identity(
        self, *, run_id: str, thread_id: str, turn_id: str
    ) -> None:
        with self.database.session() as connection:
            connection.execute(
                """
                UPDATE codex_runs
                SET thread_id = ?, turn_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
                """,
                (thread_id, turn_id, run_id),
            )

    def update_codex_run_status(
        self,
        *,
        run_id: str,
        status: str,
        failure_code: str | None = None,
    ) -> None:
        if status not in {
            "starting",
            "running",
            "waiting_for_approval",
            "completed",
            "failed",
            "interrupted",
        }:
            raise ValueError(f"Unsupported Codex run status: {status}.")
        terminal = status in {"completed", "failed", "interrupted"}
        with self.database.session() as connection:
            connection.execute(
                """
                UPDATE codex_runs
                SET status = ?, failure_code = ?, updated_at = CURRENT_TIMESTAMP,
                    completed_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END
                WHERE run_id = ?
                """,
                (status, failure_code, int(terminal), run_id),
            )

    def update_codex_run_usage(
        self, *, run_id: str, usage: dict[str, Any]
    ) -> None:
        serialized = json.dumps(
            _numeric_mapping(usage), sort_keys=True, separators=(",", ":")
        )
        with self.database.session() as connection:
            connection.execute(
                """
                UPDATE codex_runs
                SET usage_json = ?, updated_at = CURRENT_TIMESTAMP
                WHERE run_id = ?
                """,
                (serialized, run_id),
            )

    def update_codex_run_liveness(
        self,
        *,
        run_id: str,
        liveness: str | None = None,
        last_event_at_ms: int | None = None,
        last_event_method: str | None = None,
        health: dict[str, Any] | None = None,
    ) -> None:
        assignments: list[str] = []
        values: list[Any] = []
        if liveness is not None:
            assignments.append("liveness = ?")
            values.append(liveness)
        if last_event_at_ms is not None:
            assignments.append("last_event_at = ?")
            values.append(int(last_event_at_ms))
        if last_event_method is not None:
            assignments.append("last_event_method = ?")
            values.append(last_event_method)
        if health is not None:
            assignments.append("health_json = ?")
            values.append(
                json.dumps(health, sort_keys=True, separators=(",", ":"))
            )
        if not assignments:
            return
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        values.append(run_id)
        query = (
            f"UPDATE codex_runs SET {', '.join(assignments)} WHERE run_id = ?"
        )
        with self.database.session() as connection:
            connection.execute(query, tuple(values))

    def get_codex_run(self, run_id: str) -> dict[str, Any] | None:
        with self.database.session() as connection:
            row = connection.execute(
                """
                SELECT run_id, decision_id, thread_id, turn_id, model, status,
                       failure_code, usage_json, last_event_at, last_event_method,
                       liveness, health_json, started_at, updated_at, completed_at
                FROM codex_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["usage"] = json.loads(result.pop("usage_json"))
        health_json = result.pop("health_json", None)
        result["health"] = json.loads(health_json) if health_json else None
        return result

    def latest_thread_usage(
        self, *, thread_id: str, exclude_run_id: str | None = None
    ) -> dict[str, Any] | None:
        query = """
            SELECT usage_json
            FROM codex_runs
            WHERE thread_id = ? AND run_id != COALESCE(?, '')
            ORDER BY updated_at DESC, rowid DESC
            LIMIT 1
        """
        with self.database.session() as connection:
            row = connection.execute(query, (thread_id, exclude_run_id)).fetchone()
        if row is None:
            return None
        usage = json.loads(row["usage_json"])
        return usage if isinstance(usage, dict) else None

    def usage_summary(self) -> dict[str, Any]:
        with self.database.session() as connection:
            totals = connection.execute(
                """
                SELECT COUNT(*) AS requests,
                       COALESCE(SUM(original_tokens), 0) AS original_tokens,
                       COALESCE(SUM(CASE WHEN candidate_tokens IS NOT NULL THEN candidate_tokens ELSE original_tokens END), 0) AS selected_path_tokens,
                       COALESCE(SUM(token_savings), 0) AS token_savings,
                       COALESCE(SUM(optimizer_cost_usd), 0) AS optimizer_cost_usd,
                       COALESCE(SUM(optimizer_cost_available), 0) AS priced_requests,
                       COALESCE(AVG(latency_ms), 0) AS average_optimizer_latency_ms
                FROM routing_decisions
                """
            ).fetchone()
            routes = connection.execute(
                "SELECT status, fallback_reason, COUNT(*) AS count FROM routing_decisions GROUP BY status, fallback_reason"
            ).fetchall()
        return {
            "requests": totals["requests"],
            "original_tokens": totals["original_tokens"],
            "selected_path_tokens": totals["selected_path_tokens"],
            "token_savings": totals["token_savings"],
            "optimizer_cost_usd": totals["optimizer_cost_usd"],
            "priced_requests": totals["priced_requests"],
            "average_optimizer_latency_ms": totals["average_optimizer_latency_ms"],
            "routes": [dict(row) for row in routes],
        }


def _numeric_mapping(value: Any) -> Any:
    """Validate that persisted Codex analytics contain numbers, nulls, and mappings only."""
    if value is None or isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {str(key): _numeric_mapping(item) for key, item in value.items()}
    raise ValueError("Codex usage persistence accepts numeric analytics only.")
