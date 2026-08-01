"""SlashToken command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slashtoken",
        description="Verified multilingual prompt routing for Codex and LLM APIs.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    ui = subcommands.add_parser("ui", help="Start the localhost approval client.")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-open", action="store_true", help="Do not open a browser.")

    subcommands.add_parser("mcp", help="Run the local stdio MCP server.")

    benchmark = subcommands.add_parser("benchmark", help="Run versioned synthetic fixtures.")
    benchmark.add_argument(
        "--fixtures",
        default="benchmarks/fixtures/prompts.jsonl",
        help="Path to authorized JSONL benchmark fixtures.",
    )
    benchmark.add_argument("--model", required=True, help="Target model/tokenizer identifier.")
    benchmark.add_argument(
        "--dry-run", action="store_true", help="Analyze fixtures without hosted provider calls."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "ui":
        return _run_ui(host=args.host, port=args.port, open_browser=not args.no_open)
    if args.command == "mcp":
        from slashtoken.mcp.server import run_mcp_server

        run_mcp_server()
        return 0
    if args.command == "benchmark":
        from slashtoken.benchmarking import run_benchmark
        from slashtoken.runtime import build_runtime

        runtime = build_runtime()
        report = run_benchmark(
            runtime,
            fixture_path=args.fixtures,
            target_model=args.model,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    raise AssertionError(f"Unhandled command: {args.command}")


def _run_ui(*, host: str, port: int, open_browser: bool) -> int:
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError(
            "Install SlashToken dependencies before starting the UI: pip install -e ."
        ) from error
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(f"http://{host}:{port}",)).start()
    uvicorn.run("slashtoken.web.app:create_app", factory=True, host=host, port=port)
    return 0


if __name__ == "__main__":
    sys.exit(main())

