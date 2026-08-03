"""Async JSON-RPC client for the local Codex App Server stdio transport."""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from slashtoken.core.models import WorkloadMode


CHATBOT_OUTPUT_POLICY = (
    "Answer professionally and completely. Remove repetition, filler, and unnecessary "
    "framing only. Preserve every substantive qualification, caveat, example, requested "
    "detail, output format, and the user's requested response language."
)

AGENTIC_OUTPUT_POLICY = (
    "Keep progress and final narration concise and professional. Implement the smallest "
    "correct change without reducing requested functionality, validation, tests, security, "
    "accessibility, architecture, or explanation needed to use the result."
)


class CodexAppServerError(RuntimeError):
    """Raised for process, transport, or JSON-RPC failures."""

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


def build_thread_overrides(
    *, output_optimization: bool, workload_mode: WorkloadMode
) -> dict[str, Any]:
    """Build thread-level output policy without editing global Codex configuration."""
    if not output_optimization:
        return {}
    mode = WorkloadMode(workload_mode)
    policy = (
        CHATBOT_OUTPUT_POLICY
        if mode == WorkloadMode.CHATBOT
        else AGENTIC_OUTPUT_POLICY
    )
    return {
        "config": {"model_verbosity": "low"},
        "developerInstructions": policy,
    }


def build_turn_params(
    *, thread_id: str, selected_prompt: str, model: str | None = None
) -> dict[str, Any]:
    """Create a turn containing exactly one selected prompt."""
    prompt = selected_prompt.strip()
    if not prompt:
        raise ValueError("selected_prompt cannot be empty.")
    params: dict[str, Any] = {
        "threadId": thread_id,
        "input": [{"type": "text", "text": prompt}],
    }
    if model:
        params["model"] = model
    return params


class CodexAppServerClient:
    def __init__(
        self,
        command: tuple[str, ...] = ("codex", "app-server"),
        *,
        request_timeout_seconds: float = 30.0,
        stderr_limit_bytes: int = 65_536,
        stream_limit_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.command = command
        self.request_timeout_seconds = request_timeout_seconds
        self.stderr_limit_bytes = stderr_limit_bytes
        self.stream_limit_bytes = stream_limit_bytes
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._notifications: asyncio.Queue[dict[str, Any] | CodexAppServerError] = (
            asyncio.Queue()
        )
        self._server_requests: dict[int | str, dict[str, Any]] = {}
        self._stderr_lines: deque[str] = deque()
        self._stderr_bytes = 0
        self._request_id = 0
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._transport_failed = False
        self._reader_failed = False
        self._stderr_failed = False

    async def start(self) -> None:
        if self._process is not None:
            return
        self._closing = False
        self._transport_failed = False
        self._reader_failed = False
        self._stderr_failed = False
        self._notifications = asyncio.Queue()
        self._server_requests.clear()
        self._stderr_lines.clear()
        self._stderr_bytes = 0
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self.stream_limit_bytes,
            )
        except FileNotFoundError as error:
            raise CodexAppServerError("The 'codex' executable was not found on PATH.") from error
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "slashtoken",
                        "title": "SlashToken",
                        "version": "0.1.0",
                    }
                },
            )
            await self.notify("initialized", {})
        except BaseException:
            await self.close()
            raise

    async def close(self) -> None:
        self._closing = True
        process = self._process
        self._process = None
        if process and process.returncode is None:
            process.terminate()
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=3)
            if process.returncode is None:
                process.kill()
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        error = CodexAppServerError("Codex App Server connection closed.")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        self._server_requests.clear()

    async def request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self._ensure_running()
        self._request_id += 1
        request_id = self._request_id
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send(
                {"method": method, "id": request_id, "params": params or {}}
            )
            return await asyncio.wait_for(
                asyncio.shield(future), timeout=self.request_timeout_seconds
            )
        except asyncio.TimeoutError as error:
            if not future.done():
                future.cancel()
            raise CodexAppServerError(
                f"Codex App Server request timed out: {method}."
            ) from error
        except BaseException:
            if not future.done():
                future.cancel()
            raise
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._ensure_running()
        await self._send({"method": method, "params": params or {}})

    async def respond(self, request_id: int | str, result: dict[str, Any]) -> None:
        """Respond to a server-initiated approval or user-input request."""
        self._ensure_running()
        if request_id not in self._server_requests:
            raise CodexAppServerError("Codex server request is no longer pending.")
        await self._send({"id": request_id, "result": result})

    async def respond_error(
        self, request_id: int | str, *, code: int, message: str
    ) -> None:
        self._ensure_running()
        if request_id not in self._server_requests:
            raise CodexAppServerError("Codex server request is no longer pending.")
        await self._send(
            {"id": request_id, "error": {"code": code, "message": message}}
        )

    @property
    def pending_server_requests(self) -> dict[int | str, dict[str, Any]]:
        """Return a shallow copy of currently unresolved server requests."""
        return dict(self._server_requests)

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        """Return bounded, process-local diagnostics without persisting them."""
        return tuple(self._stderr_lines)

    def health_snapshot(self) -> dict[str, Any]:
        """Return privacy-safe transport diagnostics.

        Contains only booleans, counts, and a process return code. It never
        includes stderr text, file paths, prompts, or any request payload.
        """
        process = self._process
        reader = self._reader_task
        stderr = self._stderr_task
        return {
            "process_running": bool(process is not None and process.returncode is None),
            "returncode": process.returncode if process is not None else None,
            "reader_task_done": bool(reader is not None and reader.done()),
            "reader_task_failed": self._reader_failed,
            "stderr_task_done": bool(stderr is not None and stderr.done()),
            "stderr_task_failed": self._stderr_failed,
            "pending_request_count": len(self._pending),
            "pending_server_request_count": len(self._server_requests),
            "transport_failed": self._transport_failed,
            "stderr_line_count": len(self._stderr_lines),
        }

    async def check_liveness(self) -> bool:
        """Wake a blocked notification consumer if the transport is provably dead.

        Returns True when a transport failure was raised as a result of this
        probe. A live-but-quiet transport returns False and is left untouched.
        """
        if self._transport_failed or self._closing:
            return False
        process = self._process
        reader = self._reader_task
        if process is not None and process.returncode is not None:
            await self._fail_transport(
                CodexAppServerError(
                    f"Codex App Server exited unexpectedly (code {process.returncode}).",
                    code="app_server_exited",
                )
            )
            return True
        if reader is not None and reader.done():
            self._reader_failed = True
            await self._fail_transport(
                CodexAppServerError(
                    "Codex App Server stdout reader is no longer running.",
                    code="stdout_reader_failed",
                )
            )
            return True
        return False

    async def list_models(self) -> list[dict[str, Any]]:
        result = await self.request("model/list", {"limit": 100, "includeHidden": False})
        data = result.get("data", [])
        return data if isinstance(data, list) else []

    async def start_thread(
        self,
        *,
        cwd: str,
        model: str | None,
        output_optimization: bool,
        workload_mode: WorkloadMode,
    ) -> str:
        params: dict[str, Any] = {
            "cwd": cwd,
            "serviceName": "slashtoken",
            **build_thread_overrides(
                output_optimization=output_optimization,
                workload_mode=workload_mode,
            ),
        }
        if model:
            params["model"] = model
        result = await self.request("thread/start", params)
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise CodexAppServerError("thread/start returned no thread id.")
        return thread["id"]

    async def resume_thread(
        self,
        *,
        thread_id: str,
        cwd: str,
        model: str | None,
        output_optimization: bool,
        workload_mode: WorkloadMode,
    ) -> str:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "cwd": cwd,
            **build_thread_overrides(
                output_optimization=output_optimization,
                workload_mode=workload_mode,
            ),
        }
        if model:
            params["model"] = model
        result = await self.request("thread/resume", params)
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise CodexAppServerError("thread/resume returned no thread id.")
        return thread["id"]

    async def start_turn(
        self, *, thread_id: str, selected_prompt: str, model: str | None = None
    ) -> str:
        result = await self.request(
            "turn/start",
            build_turn_params(
                thread_id=thread_id,
                selected_prompt=selected_prompt,
                model=model,
            ),
        )
        turn = result.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise CodexAppServerError("turn/start returned no turn id.")
        return turn["id"]

    async def interrupt_turn(self, *, thread_id: str, turn_id: str) -> None:
        await self.request("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})

    async def notifications(self, *, turn_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        while True:
            message = await self._notifications.get()
            if isinstance(message, CodexAppServerError):
                raise message
            message_turn_id = _message_turn_id(message)
            if turn_id and message_turn_id and message_turn_id != turn_id:
                continue
            yield message
            if message.get("method") == "turn/completed" and (
                turn_id is None or message_turn_id == turn_id
            ):
                return

    async def _send(self, message: dict[str, Any]) -> None:
        process = self._ensure_running()
        if process.stdin is None:
            raise CodexAppServerError("Codex App Server stdin is unavailable.")
        encoded = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        async with self._write_lock:
            process.stdin.write(encoded)
            await process.stdin.drain()

    async def _read_stdout(self) -> None:
        try:
            process = self._ensure_running()
            assert process.stdout is not None
            while line := await process.stdout.readline():
                await self._dispatch(line)
            if not self._closing:
                returncode = await process.wait()
                await self._fail_transport(
                    CodexAppServerError(
                        f"Codex App Server exited unexpectedly (code {returncode}).",
                        code="app_server_exited",
                    )
                )
        except asyncio.CancelledError:
            raise
        except ValueError as error:
            # asyncio.StreamReader.readline() raises ValueError when a line
            # exceeds the configured stream limit before a newline is found.
            self._reader_failed = True
            await self._fail_transport(
                CodexAppServerError(
                    "Codex App Server emitted a stdout line beyond the configured "
                    f"stream limit of {self.stream_limit_bytes} bytes: {error}.",
                    code="stdout_line_limit_exceeded",
                )
            )
        except Exception as error:
            self._reader_failed = True
            await self._fail_transport(
                CodexAppServerError(
                    f"Codex App Server stdout reader failed: {error}.",
                    code="stdout_reader_failed",
                )
            )

    async def _dispatch(self, line: bytes) -> None:
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            self._reader_failed = True
            await self._fail_transport(
                CodexAppServerError(
                    f"Codex App Server returned invalid JSON: {error.msg}.",
                    code="invalid_json",
                )
            )
            raise
        if not isinstance(message, dict):
            return
        request_id = message.get("id")
        method = message.get("method")
        if isinstance(method, str):
            if request_id is not None and isinstance(request_id, (int, str)):
                self._server_requests[request_id] = message
            if method == "serverRequest/resolved":
                params = message.get("params")
                resolved_id = params.get("requestId") if isinstance(params, dict) else None
                if isinstance(resolved_id, (int, str)):
                    self._server_requests.pop(resolved_id, None)
            await self._notifications.put(message)
        elif isinstance(request_id, int) and request_id in self._pending:
            future = self._pending.pop(request_id)
            if "error" in message:
                error = message["error"]
                future.set_exception(CodexAppServerError(str(error)))
            else:
                result = message.get("result", {})
                future.set_result(result if isinstance(result, dict) else {})

    async def _drain_stderr(self) -> None:
        try:
            process = self._ensure_running()
            assert process.stderr is not None
            while line := await process.stderr.readline():
                decoded = line.decode("utf-8", errors="replace")
                encoded_size = len(decoded.encode("utf-8"))
                self._stderr_lines.append(decoded)
                self._stderr_bytes += encoded_size
                while self._stderr_lines and self._stderr_bytes > self.stderr_limit_bytes:
                    removed = self._stderr_lines.popleft()
                    self._stderr_bytes -= len(removed.encode("utf-8"))
        except asyncio.CancelledError:
            raise
        except Exception:
            # Stderr is diagnostics only. A dead stderr reader is recorded so the
            # health snapshot can surface it, but it must not fail the transport.
            self._stderr_failed = True

    async def _fail_transport(self, error: CodexAppServerError) -> None:
        if self._transport_failed or self._closing:
            return
        self._transport_failed = True
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        await self._notifications.put(error)

    def _ensure_running(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise CodexAppServerError("Codex App Server client has not been started.")
        return self._process


def _message_turn_id(message: dict[str, Any]) -> str | None:
    params = message.get("params")
    if not isinstance(params, dict):
        return None
    direct = params.get("turnId")
    if isinstance(direct, str):
        return direct
    turn = params.get("turn")
    if isinstance(turn, dict) and isinstance(turn.get("id"), str):
        return turn["id"]
    return None
