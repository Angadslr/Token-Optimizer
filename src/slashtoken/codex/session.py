"""One browser-visible Codex conversation managed through App Server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from slashtoken.codex.app_server import CodexAppServerClient
from slashtoken.core.models import WorkloadMode


class CodexSession:
    def __init__(self, client: CodexAppServerClient) -> None:
        self.client = client
        self.thread_id: str | None = None
        self.turn_id: str | None = None

    async def connect(self) -> None:
        await self.client.start()

    async def models(self) -> list[dict[str, Any]]:
        return await self.client.list_models()

    async def submit(
        self,
        *,
        selected_prompt: str,
        project_path: str,
        model: str | None,
        output_optimization: bool,
        workload_mode: WorkloadMode,
        resume_thread_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        await self.start_submission(
            selected_prompt=selected_prompt,
            project_path=project_path,
            model=model,
            output_optimization=output_optimization,
            workload_mode=workload_mode,
            resume_thread_id=resume_thread_id,
        )
        async for event in self.events():
            yield event

    async def start_submission(
        self,
        *,
        selected_prompt: str,
        project_path: str,
        model: str | None,
        output_optimization: bool,
        workload_mode: WorkloadMode,
        resume_thread_id: str | None = None,
    ) -> tuple[str, str]:
        """Start one turn and return its acknowledged thread and turn IDs."""
        cwd = str(Path(project_path).expanduser().resolve())
        if resume_thread_id and self.thread_id != resume_thread_id:
            self.thread_id = await self.client.resume_thread(
                thread_id=resume_thread_id,
                cwd=cwd,
                model=model,
                output_optimization=output_optimization,
                workload_mode=workload_mode,
            )
        elif self.thread_id is None:
            self.thread_id = await self.client.start_thread(
                cwd=cwd,
                model=model,
                output_optimization=output_optimization,
                workload_mode=workload_mode,
            )
        self.turn_id = await self.client.start_turn(
            thread_id=self.thread_id,
            selected_prompt=selected_prompt,
            model=model,
        )
        return self.thread_id, self.turn_id

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        if self.turn_id is None:
            raise RuntimeError("No Codex turn has been started.")
        async for event in self.client.notifications(turn_id=self.turn_id):
            yield event

    async def interrupt(self) -> None:
        if self.thread_id and self.turn_id:
            await self.client.interrupt_turn(thread_id=self.thread_id, turn_id=self.turn_id)

    async def close(self) -> None:
        await self.client.close()
