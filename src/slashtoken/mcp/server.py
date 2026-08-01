"""Local stdio MCP server backed by the shared SlashToken runtime."""

from __future__ import annotations

from typing import Any

from slashtoken.core.models import OptimizationRequest, ResponseLanguage, WorkloadMode
from slashtoken.core.pipeline import response_language_name
from slashtoken.runtime import SlashTokenRuntime, build_runtime, select_pending_prompt


def _request(
    *,
    prompt: str,
    target_model: str,
    project_path: str | None,
    workload_mode: str,
) -> OptimizationRequest:
    return OptimizationRequest(
        prompt=prompt,
        target_model=target_model,
        project_path=project_path,
        workload_mode=WorkloadMode(workload_mode),
        response_language=ResponseLanguage.PRESERVE_SOURCE,
    )


def register_tools(mcp: Any, runtime: SlashTokenRuntime) -> None:
    """Register tools separately so contract tests can use a fake FastMCP object."""

    @mcp.tool()
    def analyze_prompt(
        prompt: str,
        target_model: str,
        project_path: str | None = None,
        workload_mode: str = WorkloadMode.AGENTIC_CODING.value,
    ) -> dict[str, Any]:
        """Analyze language, risk, protected spans, and original target-model tokens."""
        request = _request(
            prompt=prompt,
            target_model=target_model,
            project_path=project_path,
            workload_mode=workload_mode,
        )
        analysis = runtime.pipeline.analyze(request)
        return {
            "source_language": analysis.source_language,
            "supported": analysis.supported,
            "high_stakes": analysis.high_stakes,
            "risk_categories": list(analysis.risk_categories),
            "protected_spans": [
                {"kind": span.kind, "value": span.value} for span in analysis.protected_spans
            ],
            "original_tokens": {
                "tokens": analysis.original_tokens.tokens,
                "exact": analysis.original_tokens.exact,
                "tokenizer": analysis.original_tokens.tokenizer,
            },
        }

    @mcp.tool()
    def optimize_prompt(
        prompt: str,
        target_model: str,
        project_path: str | None = None,
        session_id: str | None = None,
        workload_mode: str = WorkloadMode.AGENTIC_CODING.value,
    ) -> dict[str, Any]:
        """Return a verified candidate for approval; never execute it."""
        request = _request(
            prompt=prompt,
            target_model=target_model,
            project_path=project_path,
            workload_mode=workload_mode,
        )
        settings = runtime.settings.resolve(
            project_path=project_path, session_id=session_id
        )
        decision = runtime.pipeline.optimize(
            request, language_optimization=settings.language_optimization
        )
        runtime.decisions.put(request, decision)
        return decision.public_dict()

    @mcp.tool()
    def run_chat(
        decision_id: str,
        selection: str = "candidate",
        edited_prompt: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute one route from a previously displayed optimize_prompt decision."""
        pending, selected_prompt = select_pending_prompt(
            runtime,
            decision_id=decision_id,
            selection=selection,
            edited_prompt=edited_prompt,
        )
        settings = runtime.settings.resolve(
            project_path=pending.request.project_path, session_id=session_id
        )
        result = runtime.provider.chat(
            prompt=selected_prompt,
            response_language=(
                response_language_name(pending.decision.source_language)
                if settings.response_language.value == "preserve_source"
                else "English"
            ),
            workload_mode=settings.workload_mode,
            output_optimization=settings.output_optimization,
        )
        runtime.repository.record_approval(
            pending.decision.decision_id, selection, "mcp"
        )
        runtime.decisions.consume(decision_id)
        return {
            "response": result.response,
            "selected_route": selection,
            "decision_id": decision_id,
            "usage": {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "estimated_cost_usd": result.usage.estimated_cost_usd,
                "latency_ms": result.usage.latency_ms,
            },
        }

    @mcp.tool()
    def settings_get(
        project_path: str | None = None, session_id: str | None = None
    ) -> dict[str, Any]:
        """Return effective SlashToken settings after scope resolution."""
        return runtime.settings.resolve(
            project_path=project_path, session_id=session_id
        ).to_dict()

    @mcp.tool()
    def settings_update(
        scope: str,
        values: dict[str, Any],
        project_path: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Update an explicit local user, project, or session settings scope."""
        return runtime.settings.update(
            scope=scope,
            values=values,
            project_path=project_path,
            session_id=session_id,
        ).to_dict()

    @mcp.tool()
    def usage_summary() -> dict[str, Any]:
        """Return aggregate, content-free routing and token metrics."""
        return runtime.repository.usage_summary()


def create_mcp_server(runtime: SlashTokenRuntime | None = None):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "Install SlashToken dependencies before running the MCP server: pip install -e ."
        ) from error
    server = FastMCP("SlashToken")
    register_tools(server, runtime or build_runtime())
    return server


def run_mcp_server() -> None:
    create_mcp_server().run(transport="stdio")
