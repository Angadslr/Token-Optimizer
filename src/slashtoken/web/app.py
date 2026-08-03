"""FastAPI approval UI and local API over the shared SlashToken runtime."""

from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from slashtoken.codex.runs import CodexRunManager
from slashtoken.core.models import (
    OptimizationRequest,
    ResponseLanguage,
    WorkloadMode,
)
from slashtoken.core.pipeline import response_language_name
from slashtoken.providers.base import ProviderUnavailableError
from slashtoken.runtime import (
    SlashTokenRuntime,
    build_runtime,
    select_pending_prompt,
)


class PromptBody(BaseModel):
    prompt: str = Field(min_length=1)
    target_model: str = Field(min_length=1)
    project_path: str | None = None
    session_id: str | None = None
    workload_mode: WorkloadMode = WorkloadMode.AGENTIC_CODING


class SettingsPatchBody(BaseModel):
    scope: Literal["user", "project", "session"]
    values: dict[str, Any]
    project_path: str | None = None
    session_id: str | None = None


class ChatBody(BaseModel):
    decision_id: str
    selection: Literal["candidate", "original"]
    edited_prompt: str | None = None
    session_id: str | None = None


def create_app(
    runtime: SlashTokenRuntime | None = None,
    run_manager: CodexRunManager | None = None,
):
    resolved_runtime = runtime or build_runtime()
    resolved_run_manager = run_manager or CodexRunManager(resolved_runtime)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await resolved_run_manager.close()

    app = FastAPI(title="SlashToken", version="0.1.0", lifespan=lifespan)
    app.state.runtime = resolved_runtime
    app.state.codex_runs = resolved_run_manager
    package_dir = Path(__file__).resolve().parent
    static_version = max(
        (package_dir / "static" / filename).stat().st_mtime_ns
        for filename in ("app.js", "styles.css")
    )
    templates = Jinja2Templates(directory=package_dir / "templates")
    app.mount("/static", StaticFiles(directory=package_dir / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "default_project": str(Path.cwd()),
                "static_version": static_version,
            },
        )

    @app.post("/api/analyze")
    async def analyze(body: PromptBody):
        request = _optimization_request(body)
        try:
            result = await asyncio.to_thread(app.state.runtime.pipeline.analyze, request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {
            "source_language": result.source_language,
            "supported": result.supported,
            "high_stakes": result.high_stakes,
            "risk_categories": list(result.risk_categories),
            "protected_spans": [
                {"kind": span.kind, "value": span.value} for span in result.protected_spans
            ],
            "original_tokens": {
                "tokens": result.original_tokens.tokens,
                "exact": result.original_tokens.exact,
                "tokenizer": result.original_tokens.tokenizer,
            },
        }

    @app.post("/api/optimize")
    async def optimize(body: PromptBody):
        request = _optimization_request(body)
        settings = app.state.runtime.settings.resolve(
            project_path=body.project_path, session_id=body.session_id
        )
        decision = await asyncio.to_thread(
            app.state.runtime.pipeline.optimize,
            request,
            language_optimization=settings.language_optimization,
        )
        app.state.runtime.decisions.put(request, decision)
        payload = decision.public_dict()
        payload["effective_settings"] = settings.to_dict()
        payload["should_auto_run"] = bool(
            settings.approval_policy.value == "auto_verified"
            and decision.auto_run_eligible
        )
        return payload

    @app.post("/api/chat")
    async def chat(body: ChatBody):
        try:
            pending, selected_prompt = await asyncio.to_thread(
                select_pending_prompt,
                app.state.runtime,
                decision_id=body.decision_id,
                selection=body.selection,
                edited_prompt=body.edited_prompt,
            )
            settings = app.state.runtime.settings.resolve(
                project_path=pending.request.project_path,
                session_id=body.session_id,
            )
            result = await asyncio.to_thread(
                app.state.runtime.provider.chat,
                prompt=selected_prompt,
                response_language=(
                    response_language_name(pending.decision.source_language)
                    if settings.response_language == ResponseLanguage.PRESERVE_SOURCE
                    else "English"
                ),
                workload_mode=settings.workload_mode,
                output_optimization=settings.output_optimization,
            )
            app.state.runtime.repository.record_approval(
                pending.decision.decision_id, body.selection, None
            )
            app.state.runtime.decisions.consume(body.decision_id)
            return {
                "response": result.response,
                "selected_route": body.selection,
                "decision_id": body.decision_id,
                "usage": {
                    "input_tokens": result.usage.input_tokens,
                    "output_tokens": result.usage.output_tokens,
                    "estimated_cost_usd": result.usage.estimated_cost_usd,
                    "latency_ms": result.usage.latency_ms,
                },
            }
        except ProviderUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/settings")
    async def get_settings(project_path: str | None = None, session_id: str | None = None):
        return app.state.runtime.settings.resolve(
            project_path=project_path, session_id=session_id
        ).to_dict()

    @app.patch("/api/settings")
    async def patch_settings(body: SettingsPatchBody):
        try:
            settings = app.state.runtime.settings.update(
                scope=body.scope,
                values=body.values,
                project_path=body.project_path,
                session_id=body.session_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return settings.to_dict()

    @app.get("/api/usage")
    async def usage():
        return app.state.runtime.repository.usage_summary()

    @app.websocket("/ws/codex")
    async def codex_socket(websocket: WebSocket):
        await websocket.accept()
        browser_session_id: str | None = None
        subscription: asyncio.Queue[dict[str, Any]] | None = None
        sender_task: asyncio.Task[None] | None = None
        send_lock = asyncio.Lock()

        async def send(payload: dict[str, Any]) -> None:
            async with send_lock:
                await websocket.send_json(payload)

        async def forward_events(queue: asyncio.Queue[dict[str, Any]]) -> None:
            while True:
                await send(await queue.get())

        try:
            await send({"type": "connected"})
            while True:
                message = await websocket.receive_json()
                action = message.get("action")
                if action == "attach":
                    if browser_session_id is not None:
                        await send(
                            {"type": "error", "message": "WebSocket is already attached."}
                        )
                        continue
                    candidate_session_id = message.get("session_id")
                    if not isinstance(candidate_session_id, str):
                        await send(
                            {"type": "error", "message": "A browser session id is required."}
                        )
                        continue
                    requested_run_id = message.get("run_id")
                    if requested_run_id is not None and not isinstance(
                        requested_run_id, str
                    ):
                        await send(
                            {"type": "error", "message": "Invalid Codex run id."}
                        )
                        continue
                    browser_session_id = candidate_session_id
                    subscription, snapshot = await app.state.codex_runs.attach(
                        session_id=browser_session_id,
                        requested_run_id=requested_run_id,
                    )
                    await send(
                        {
                            "type": "attached",
                            "session_id": browser_session_id,
                            "silence_warning_seconds": (
                                app.state.codex_runs.config.silence_warning_seconds
                            ),
                            "idle_diagnostic_seconds": (
                                app.state.codex_runs.config.idle_diagnostic_seconds
                            ),
                        }
                    )
                    if snapshot:
                        await send(snapshot)
                    sender_task = asyncio.create_task(forward_events(subscription))
                elif browser_session_id is None:
                    await send(
                        {"type": "error", "message": "Attach before using Codex."}
                    )
                elif action == "models":
                    await send(
                        {
                            "type": "models",
                            "models": await app.state.codex_runs.models(
                                browser_session_id
                            ),
                        }
                    )
                elif action == "interrupt":
                    run_id = message.get("run_id")
                    if not isinstance(run_id, str):
                        await send(
                            {"type": "error", "message": "A Codex run id is required."}
                        )
                    else:
                        await app.state.codex_runs.interrupt(
                            session_id=browser_session_id, run_id=run_id
                        )
                elif action == "approval_response":
                    request_id = message.get("request_id")
                    decision = message.get("decision")
                    run_id = message.get("run_id")
                    if (
                        not isinstance(request_id, (int, str))
                        or not isinstance(decision, str)
                        or not isinstance(run_id, str)
                    ):
                        await send(
                            {"type": "error", "message": "Invalid approval response."}
                        )
                    else:
                        await app.state.codex_runs.respond_to_approval(
                            session_id=browser_session_id,
                            run_id=run_id,
                            request_id=request_id,
                            decision=decision,
                        )
                elif action == "submit":
                    run_id = await app.state.codex_runs.submit(
                        session_id=browser_session_id,
                        decision_id=str(message["decision_id"]),
                        selection=str(message["selection"]),
                        edited_prompt=message.get("edited_prompt"),
                        resume_thread_id=message.get("thread_id"),
                    )
                    await send(
                        {
                            "type": "submitted",
                            "decision_id": str(message["decision_id"]),
                            "run_id": run_id,
                        }
                    )
                else:
                    await send(
                        {"type": "error", "message": "Unknown WebSocket action."}
                    )
        except WebSocketDisconnect:
            pass
        except Exception as error:
            with contextlib.suppress(RuntimeError):
                await send({"type": "error", "message": _public_error(error)})
        finally:
            if sender_task:
                sender_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await sender_task
            if browser_session_id and subscription:
                await app.state.codex_runs.detach(
                    session_id=browser_session_id, queue=subscription
                )

    return app


def _optimization_request(body: PromptBody) -> OptimizationRequest:
    return OptimizationRequest(
        prompt=body.prompt,
        target_model=body.target_model,
        project_path=body.project_path,
        workload_mode=body.workload_mode,
        response_language=ResponseLanguage.PRESERVE_SOURCE,
    )


def _public_error(error: BaseException) -> str:
    if isinstance(error, (KeyError, ValueError)):
        return str(error).strip("'")
    return f"Codex operation failed ({type(error).__name__})."
