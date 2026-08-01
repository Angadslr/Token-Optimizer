"""Reload-safe orchestration for browser-visible Codex runs."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from slashtoken.codex.app_server import CodexAppServerClient, CodexAppServerError
from slashtoken.codex.session import CodexSession
from slashtoken.core.models import WorkloadMode
from slashtoken.runtime import SlashTokenRuntime, select_pending_prompt


TERMINAL_STATUSES = {"completed", "failed", "interrupted"}
APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}
STRING_APPROVAL_DECISIONS = {
    "accept",
    "acceptForSession",
    "decline",
    "cancel",
}


@dataclass(frozen=True, slots=True)
class CodexRunConfig:
    approval_timeout_seconds: float = 600.0
    disconnected_grace_seconds: float = 600.0
    approval_resolution_seconds: float = 10.0
    interrupt_timeout_seconds: float = 10.0
    silence_warning_seconds: float = 120.0
    replay_event_limit: int = 1_000
    replay_byte_limit: int = 1_048_576

    @classmethod
    def from_environment(cls) -> "CodexRunConfig":
        return cls(
            approval_timeout_seconds=_positive_float(
                "SLASHTOKEN_CODEX_APPROVAL_TIMEOUT_SECONDS", 600.0
            ),
            disconnected_grace_seconds=_positive_float(
                "SLASHTOKEN_CODEX_DISCONNECT_GRACE_SECONDS", 600.0
            ),
            approval_resolution_seconds=_positive_float(
                "SLASHTOKEN_CODEX_APPROVAL_RESOLUTION_SECONDS", 10.0
            ),
            interrupt_timeout_seconds=_positive_float(
                "SLASHTOKEN_CODEX_INTERRUPT_TIMEOUT_SECONDS", 10.0
            ),
            silence_warning_seconds=_positive_float(
                "SLASHTOKEN_CODEX_SILENCE_WARNING_SECONDS", 120.0
            ),
        )


@dataclass(slots=True)
class PendingApproval:
    request_id: int | str
    method: str
    params: dict[str, Any]
    available_decisions: tuple[str, ...]
    expires_at_ms: int
    response_decision: str | None = None
    automatic_response: bool = False
    resolved: asyncio.Event = field(default_factory=asyncio.Event)
    timeout_task: asyncio.Task[None] | None = None
    response_watchdog: asyncio.Task[None] | None = None

    def public_dict(self) -> dict[str, Any]:
        network_context = self.params.get("networkApprovalContext")
        if isinstance(network_context, dict):
            kind = "network"
        elif self.method == "item/fileChange/requestApproval":
            kind = "file_change"
        else:
            kind = "command"
        return {
            "request_id": self.request_id,
            "method": self.method,
            "kind": kind,
            "reason": _optional_text(self.params.get("reason")),
            "command": _optional_text(self.params.get("command")),
            "cwd": _optional_text(self.params.get("cwd")),
            "grant_root": _optional_text(self.params.get("grantRoot")),
            "network_context": network_context if isinstance(network_context, dict) else None,
            "available_decisions": list(self.available_decisions),
            "expires_at_ms": self.expires_at_ms,
            "response_decision": self.response_decision,
        }


@dataclass(slots=True, eq=False)
class CodexRun:
    run_id: str
    browser_session_id: str
    decision_id: str
    model: str
    status: str = "starting"
    thread_id: str | None = None
    turn_id: str | None = None
    failure_code: str | None = None
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    completed_at_ms: int | None = None
    last_event_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    usage: dict[str, Any] = field(default_factory=dict)
    baseline_usage: dict[str, int] | None = None
    events: deque[dict[str, Any]] = field(default_factory=deque)
    event_bytes: int = 0
    replay_truncated: bool = False
    approvals: dict[int | str, PendingApproval] = field(default_factory=dict)
    terminal_event: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None
    escalation_task: asyncio.Task[None] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "decision_id": self.decision_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "model": self.model,
            "status": self.status,
            "failure_code": self.failure_code,
            "started_at_ms": self.started_at_ms,
            "completed_at_ms": self.completed_at_ms,
            "last_event_at_ms": self.last_event_at_ms,
            "usage": self.usage,
            "pending_approvals": [
                approval.public_dict() for approval in self.approvals.values()
            ],
        }


@dataclass(slots=True, eq=False)
class BrowserCodexSession:
    session_id: str
    codex: CodexSession
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    active_run: CodexRun | None = None
    disconnect_task: asyncio.Task[None] | None = None
    connect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CodexRunManager:
    """Own Codex processes independently from short-lived browser sockets."""

    def __init__(
        self,
        runtime: SlashTokenRuntime,
        *,
        client_factory: Callable[[], CodexAppServerClient] = CodexAppServerClient,
        config: CodexRunConfig | None = None,
    ) -> None:
        self.runtime = runtime
        self.client_factory = client_factory
        self.config = config or CodexRunConfig.from_environment()
        self._sessions: dict[str, BrowserCodexSession] = {}
        self._lock = asyncio.Lock()

    async def attach(
        self, *, session_id: str, requested_run_id: str | None
    ) -> tuple[asyncio.Queue[dict[str, Any]], dict[str, Any] | None]:
        session = await self._get_or_create_session(session_id)
        if session.disconnect_task:
            session.disconnect_task.cancel()
            session.disconnect_task = None
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2_000)
        session.subscribers.add(queue)
        run = session.active_run
        if run and (
            run.status not in TERMINAL_STATUSES
            or requested_run_id is None
            or requested_run_id == run.run_id
        ):
            return queue, self._snapshot(run)
        if requested_run_id:
            persisted = await asyncio.to_thread(
                self.runtime.repository.get_codex_run, requested_run_id
            )
            if persisted is not None:
                return queue, {
                    "type": "run_snapshot",
                    "run": _persisted_public_run(persisted),
                    "events": [],
                    "replay_truncated": True,
                }
        return queue, None

    async def detach(
        self, *, session_id: str, queue: asyncio.Queue[dict[str, Any]]
    ) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            return
        session.subscribers.discard(queue)
        run = session.active_run
        if session.subscribers:
            return
        if session.disconnect_task:
            session.disconnect_task.cancel()
        session.disconnect_task = asyncio.create_task(
            self._disconnect_watchdog(session, run)
        )

    async def models(self, session_id: str) -> list[dict[str, Any]]:
        session = await self._get_or_create_session(session_id)
        await self._ensure_connected(session)
        return await session.codex.models()

    async def submit(
        self,
        *,
        session_id: str,
        decision_id: str,
        selection: str,
        edited_prompt: str | None,
        resume_thread_id: str | None,
    ) -> str:
        session = await self._get_or_create_session(session_id)
        if session.active_run and session.active_run.status not in TERMINAL_STATUSES:
            raise RuntimeError("A Codex turn is already running in this browser session.")
        pending, selected_prompt = await asyncio.to_thread(
            select_pending_prompt,
            self.runtime,
            decision_id=decision_id,
            selection=selection,
            edited_prompt=edited_prompt,
        )
        settings = self.runtime.settings.resolve(
            project_path=pending.request.project_path,
            session_id=session_id,
        )
        run = CodexRun(
            run_id=str(uuid.uuid4()),
            browser_session_id=session_id,
            decision_id=decision_id,
            model=pending.request.target_model,
        )
        await asyncio.to_thread(
            self.runtime.repository.create_codex_run,
            run_id=run.run_id,
            decision_id=decision_id,
            model=run.model,
            project_path=pending.request.project_path,
        )
        session.active_run = run
        run.task = asyncio.create_task(
            self._execute(
                session=session,
                run=run,
                selected_prompt=selected_prompt,
                project_path=pending.request.project_path or os.getcwd(),
                output_optimization=settings.output_optimization,
                workload_mode=settings.workload_mode,
                resume_thread_id=resume_thread_id,
                selection=selection,
            )
        )
        return run.run_id

    async def respond_to_approval(
        self,
        *,
        session_id: str,
        run_id: str,
        request_id: int | str,
        decision: str,
        automatic: bool = False,
    ) -> None:
        session, run = self._active_run(session_id, run_id)
        approval = run.approvals.get(request_id)
        if approval is None or approval.resolved.is_set():
            raise ValueError("This Codex approval is stale or belongs to another run.")
        if approval.response_decision is not None:
            raise ValueError("This Codex approval already has a response pending.")
        if decision not in approval.available_decisions:
            raise ValueError("This decision is not available for the Codex approval.")
        approval.response_decision = decision
        approval.automatic_response = automatic
        try:
            await session.codex.client.respond(request_id, {"decision": decision})
        except Exception:
            approval.response_decision = None
            approval.automatic_response = False
            raise
        await self._publish(
            session,
            {
                "type": "approval_required",
                "run_id": run.run_id,
                "approval": approval.public_dict(),
            },
        )
        approval.response_watchdog = asyncio.create_task(
            self._approval_response_watchdog(session, run, approval)
        )

    async def interrupt(self, *, session_id: str, run_id: str) -> None:
        session, run = self._active_run(session_id, run_id)
        self._schedule_escalation(session, run, "user_interrupted")

    async def close(self) -> None:
        sessions = list(self._sessions.values())
        for session in sessions:
            if session.disconnect_task:
                session.disconnect_task.cancel()
            run = session.active_run
            if run and run.status not in TERMINAL_STATUSES:
                await self._finalize(
                    session,
                    run,
                    status="interrupted",
                    failure_code="backend_shutdown",
                )
            await session.codex.close()
            if run and run.task and not run.task.done():
                run.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await run.task
        self._sessions.clear()

    async def _get_or_create_session(self, session_id: str) -> BrowserCodexSession:
        if not session_id or len(session_id) > 128:
            raise ValueError("A valid browser session id is required.")
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                session = BrowserCodexSession(
                    session_id=session_id,
                    codex=CodexSession(self.client_factory()),
                )
                self._sessions[session_id] = session
            return session

    async def _ensure_connected(self, session: BrowserCodexSession) -> None:
        async with session.connect_lock:
            await session.codex.connect()

    async def _execute(
        self,
        *,
        session: BrowserCodexSession,
        run: CodexRun,
        selected_prompt: str,
        project_path: str,
        output_optimization: bool,
        workload_mode: WorkloadMode,
        resume_thread_id: str | None,
        selection: str,
    ) -> None:
        try:
            await self._ensure_connected(session)
            prior_thread_id = session.codex.thread_id or resume_thread_id
            thread_id, turn_id = await session.codex.start_submission(
                selected_prompt=selected_prompt,
                project_path=project_path,
                model=run.model,
                output_optimization=output_optimization,
                workload_mode=workload_mode,
                resume_thread_id=resume_thread_id,
            )
            run.thread_id = thread_id
            run.turn_id = turn_id
            prior_usage = await asyncio.to_thread(
                self.runtime.repository.latest_thread_usage,
                thread_id=thread_id,
                exclude_run_id=run.run_id,
            )
            prior_total = prior_usage.get("thread_total") if prior_usage else None
            if isinstance(prior_total, dict):
                run.baseline_usage = _breakdown(prior_total)
            elif prior_thread_id is None:
                run.baseline_usage = _zero_breakdown()
            await asyncio.to_thread(
                self.runtime.repository.update_codex_run_identity,
                run_id=run.run_id,
                thread_id=thread_id,
                turn_id=turn_id,
            )
            await asyncio.to_thread(self.runtime.decisions.consume, run.decision_id)
            await asyncio.to_thread(
                self.runtime.repository.record_approval,
                run.decision_id,
                selection,
                "session",
            )
            await self._set_status(session, run, "running")
            async for event in session.codex.events():
                await self._handle_event(session, run, event)
            if run.status not in TERMINAL_STATUSES:
                await self._finalize(
                    session,
                    run,
                    status="failed",
                    failure_code="stream_ended_without_completion",
                )
        except asyncio.CancelledError:
            if run.status not in TERMINAL_STATUSES:
                await self._finalize(
                    session,
                    run,
                    status="interrupted",
                    failure_code="run_task_cancelled",
                )
            raise
        except (KeyError, ValueError, RuntimeError, CodexAppServerError) as error:
            if run.status not in TERMINAL_STATUSES:
                await self._finalize(
                    session,
                    run,
                    status="failed",
                    failure_code=_exception_code(error),
                )
        except Exception as error:
            if run.status not in TERMINAL_STATUSES:
                await self._finalize(
                    session,
                    run,
                    status="failed",
                    failure_code=_exception_code(error),
                )

    async def _handle_event(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        event: dict[str, Any],
    ) -> None:
        run.last_event_at_ms = int(time.time() * 1000)
        wrapped = {"type": "codex_event", "run_id": run.run_id, "event": event}
        self._remember_event(run, wrapped)
        await self._publish(session, wrapped)
        method = event.get("method")
        params = event.get("params")
        params = params if isinstance(params, dict) else {}
        if method in APPROVAL_METHODS and isinstance(event.get("id"), (int, str)):
            await self._register_approval(session, run, event)
        elif method == "serverRequest/resolved":
            request_id = params.get("requestId")
            if isinstance(request_id, (int, str)):
                await self._resolve_approval(session, run, request_id)
        elif method == "thread/tokenUsage/updated":
            await self._record_usage(session, run, params)
        elif method == "turn/completed":
            await self._complete_from_event(session, run, params)
        elif isinstance(event.get("id"), (int, str)):
            with contextlib.suppress(CodexAppServerError):
                await session.codex.client.respond_error(
                    event["id"],
                    code=-32601,
                    message="SlashToken does not support this Codex request type.",
                )

    async def _register_approval(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        event: dict[str, Any],
    ) -> None:
        request_id = event["id"]
        if request_id in run.approvals:
            return
        params = event.get("params")
        params = params if isinstance(params, dict) else {}
        decisions = _available_decisions(params)
        approval = PendingApproval(
            request_id=request_id,
            method=str(event["method"]),
            params=params,
            available_decisions=decisions,
            expires_at_ms=int(
                (time.time() + self.config.approval_timeout_seconds) * 1000
            ),
        )
        run.approvals[request_id] = approval
        await self._set_status(session, run, "waiting_for_approval")
        await self._publish(
            session,
            {
                "type": "approval_required",
                "run_id": run.run_id,
                "approval": approval.public_dict(),
            },
        )
        approval.timeout_task = asyncio.create_task(
            self._approval_timeout(session, run, approval)
        )

    async def _resolve_approval(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        request_id: int | str,
    ) -> None:
        approval = run.approvals.pop(request_id, None)
        if approval is None:
            return
        approval.resolved.set()
        if approval.timeout_task:
            approval.timeout_task.cancel()
        await self._publish(
            session,
            {
                "type": "approval_resolved",
                "run_id": run.run_id,
                "request_id": request_id,
                "decision": approval.response_decision,
            },
        )
        if not run.approvals and run.status not in TERMINAL_STATUSES:
            await self._set_status(session, run, "running")

    async def _approval_timeout(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        approval: PendingApproval,
    ) -> None:
        try:
            await asyncio.sleep(self.config.approval_timeout_seconds)
            if approval.response_decision is None and not approval.resolved.is_set():
                await self.respond_to_approval(
                    session_id=session.session_id,
                    run_id=run.run_id,
                    request_id=approval.request_id,
                    decision="cancel",
                    automatic=True,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._schedule_escalation(session, run, "approval_timeout")

    async def _approval_response_watchdog(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        approval: PendingApproval,
    ) -> None:
        try:
            await asyncio.wait_for(
                approval.resolved.wait(),
                timeout=self.config.approval_resolution_seconds,
            )
        except asyncio.TimeoutError:
            self._schedule_escalation(session, run, "approval_unresolved")
            return
        if approval.response_decision == "cancel" and run.status not in TERMINAL_STATUSES:
            try:
                await asyncio.wait_for(
                    run.terminal_event.wait(),
                    timeout=self.config.approval_resolution_seconds,
                )
            except asyncio.TimeoutError:
                self._schedule_escalation(session, run, "approval_cancelled")

    async def _record_usage(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        params: dict[str, Any],
    ) -> None:
        token_usage = params.get("tokenUsage")
        if not isinstance(token_usage, dict):
            return
        thread_total = _breakdown(token_usage.get("total"))
        last_call = _breakdown(token_usage.get("last"))
        run_total = _subtract_breakdown(thread_total, run.baseline_usage)
        context_window = token_usage.get("modelContextWindow")
        usage: dict[str, Any] = {
            "thread_total": thread_total,
            "last_call": last_call,
            "run_total": run_total,
            "model_context_window": (
                context_window
                if isinstance(context_window, int) and not isinstance(context_window, bool)
                else None
            ),
        }
        run.usage = usage
        await asyncio.to_thread(
            self.runtime.repository.update_codex_run_usage,
            run_id=run.run_id,
            usage=usage,
        )
        await self._publish(
            session,
            {"type": "run_status", "run": run.public_dict()},
        )

    async def _complete_from_event(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        params: dict[str, Any],
    ) -> None:
        turn = params.get("turn")
        turn = turn if isinstance(turn, dict) else {}
        status = turn.get("status")
        if status not in TERMINAL_STATUSES:
            status = "failed"
        failure_code = None
        if status == "failed":
            failure_code = _turn_failure_code(turn.get("error"))
        elif status == "interrupted":
            failure_code = "turn_interrupted"
        await self._finalize(
            session,
            run,
            status=status,
            failure_code=failure_code,
        )

    async def _finalize(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        *,
        status: str,
        failure_code: str | None,
    ) -> None:
        if run.status in TERMINAL_STATUSES:
            return
        for approval in list(run.approvals.values()):
            approval.resolved.set()
            if approval.timeout_task:
                approval.timeout_task.cancel()
            if approval.response_watchdog:
                approval.response_watchdog.cancel()
        run.approvals.clear()
        run.failure_code = failure_code
        run.completed_at_ms = int(time.time() * 1000)
        run.terminal_event.set()
        await self._set_status(session, run, status, failure_code=failure_code)
        await self._publish(
            session,
            {
                "type": "turn_complete",
                "run_id": run.run_id,
                "thread_id": run.thread_id,
                "turn_id": run.turn_id,
                "status": status,
                "failure_code": failure_code,
                "started_at_ms": run.started_at_ms,
                "completed_at_ms": run.completed_at_ms,
                "usage": run.usage,
            },
        )

    async def _set_status(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        status: str,
        *,
        failure_code: str | None = None,
    ) -> None:
        run.status = status
        if failure_code is not None:
            run.failure_code = failure_code
        await asyncio.to_thread(
            self.runtime.repository.update_codex_run_status,
            run_id=run.run_id,
            status=status,
            failure_code=run.failure_code,
        )
        await self._publish(
            session,
            {"type": "run_status", "run": run.public_dict()},
        )

    def _schedule_escalation(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        reason: str,
    ) -> None:
        if run.status in TERMINAL_STATUSES:
            return
        if run.escalation_task and not run.escalation_task.done():
            return
        run.escalation_task = asyncio.create_task(
            self._interrupt_with_timeout(session, run, reason)
        )

    async def _interrupt_with_timeout(
        self,
        session: BrowserCodexSession,
        run: CodexRun,
        reason: str,
    ) -> None:
        if run.turn_id is None:
            if run.task and not run.task.done():
                run.task.cancel()
            await self._finalize(
                session, run, status="interrupted", failure_code=reason
            )
            return
        try:
            await session.codex.interrupt()
            await asyncio.wait_for(
                run.terminal_event.wait(),
                timeout=self.config.interrupt_timeout_seconds,
            )
        except asyncio.TimeoutError:
            await session.codex.close()
            await self._finalize(
                session,
                run,
                status="failed",
                failure_code="app_server_unresponsive",
            )
        except Exception as error:
            await self._finalize(
                session,
                run,
                status="failed",
                failure_code=_exception_code(error),
            )

    async def _disconnect_watchdog(
        self, session: BrowserCodexSession, run: CodexRun | None
    ) -> None:
        try:
            await asyncio.sleep(self.config.disconnected_grace_seconds)
            if (
                not session.subscribers
                and run is not None
                and run.status not in TERMINAL_STATUSES
            ):
                self._schedule_escalation(
                    session, run, "client_disconnected_timeout"
                )
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(
                        run.terminal_event.wait(),
                        timeout=(self.config.interrupt_timeout_seconds * 2) + 1,
                    )
            if not session.subscribers:
                await session.codex.close()
                async with self._lock:
                    if self._sessions.get(session.session_id) is session:
                        self._sessions.pop(session.session_id, None)
        except asyncio.CancelledError:
            raise

    def _active_run(
        self, session_id: str, run_id: str
    ) -> tuple[BrowserCodexSession, CodexRun]:
        session = self._sessions.get(session_id)
        run = session.active_run if session else None
        if run is None or run.run_id != run_id or run.status in TERMINAL_STATUSES:
            raise ValueError("The requested Codex run is not active in this session.")
        return session, run

    async def _publish(
        self, session: BrowserCodexSession, message: dict[str, Any]
    ) -> None:
        for queue in tuple(session.subscribers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(message)

    def _remember_event(self, run: CodexRun, message: dict[str, Any]) -> None:
        size = len(json.dumps(message, separators=(",", ":")).encode("utf-8"))
        run.events.append(message)
        run.event_bytes += size
        while run.events and (
            len(run.events) > self.config.replay_event_limit
            or run.event_bytes > self.config.replay_byte_limit
        ):
            removed = run.events.popleft()
            run.event_bytes -= len(
                json.dumps(removed, separators=(",", ":")).encode("utf-8")
            )
            run.replay_truncated = True

    def _snapshot(self, run: CodexRun) -> dict[str, Any]:
        return {
            "type": "run_snapshot",
            "run": run.public_dict(),
            "events": list(run.events),
            "replay_truncated": run.replay_truncated,
        }


def _available_decisions(params: dict[str, Any]) -> tuple[str, ...]:
    supplied = params.get("availableDecisions")
    if isinstance(supplied, list):
        filtered = tuple(
            decision
            for decision in supplied
            if isinstance(decision, str) and decision in STRING_APPROVAL_DECISIONS
        )
        if filtered:
            return filtered
    return ("accept", "acceptForSession", "decline", "cancel")


def _breakdown(value: Any) -> dict[str, int]:
    source = value if isinstance(value, dict) else {}
    fields = {
        "total_tokens": "totalTokens",
        "input_tokens": "inputTokens",
        "cached_input_tokens": "cachedInputTokens",
        "cache_write_input_tokens": "cacheWriteInputTokens",
        "output_tokens": "outputTokens",
        "reasoning_output_tokens": "reasoningOutputTokens",
    }
    result: dict[str, int] = {}
    for target, source_key in fields.items():
        raw = source.get(source_key, source.get(target, 0))
        result[target] = raw if isinstance(raw, int) and not isinstance(raw, bool) else 0
    return result


def _zero_breakdown() -> dict[str, int]:
    return _breakdown({})


def _subtract_breakdown(
    current: dict[str, int], baseline: dict[str, int] | None
) -> dict[str, int] | None:
    if baseline is None:
        return None
    result = {key: current[key] - baseline.get(key, 0) for key in current}
    return result if all(value >= 0 for value in result.values()) else None


def _turn_failure_code(error: Any) -> str:
    if not isinstance(error, dict):
        return "turn_failed"
    info = error.get("codexErrorInfo")
    if isinstance(info, str):
        return f"codex_{info}"
    if isinstance(info, dict) and info:
        return f"codex_{next(iter(info))}"
    return "turn_failed"


def _exception_code(error: BaseException) -> str:
    name = type(error).__name__
    normalized = "".join(
        f"_{character.lower()}" if character.isupper() else character
        for character in name
    ).lstrip("_")
    return normalized or "runtime_error"


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = float(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return parsed


def _persisted_public_run(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": record["run_id"],
        "decision_id": record["decision_id"],
        "thread_id": record["thread_id"],
        "turn_id": record["turn_id"],
        "model": record["model"],
        "status": record["status"],
        "failure_code": record["failure_code"],
        "started_at": record["started_at"],
        "updated_at": record["updated_at"],
        "completed_at": record["completed_at"],
        "usage": record["usage"],
        "pending_approvals": [],
    }
