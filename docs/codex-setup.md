# Codex Setup

## Prerequisites

- A working `codex` CLI installation and login.
- Python 3.11 or newer.
- SlashToken installed in a dedicated virtual environment.
- `NVIDIA_API_KEY` or `DEEPSEEK_API_KEY` available to the SlashToken process.

## Local approval client

```bash
slashtoken ui --host 127.0.0.1 --port 8765
```

The client starts `codex app-server` over stdio. It uses the existing Codex login,
loads models with `model/list`, creates or resumes a thread, and submits one selected
prompt with `turn/start`.

SlashToken does not weaken Codex sandbox or command-approval settings.

### Start and run a task

1. Open a terminal in the SlashToken repository and activate its virtual environment.
2. Run `slashtoken ui --host 127.0.0.1 --port 8765`.
3. Leave that terminal open. It owns the local web server and Codex App Server
   processes.
4. Open `http://127.0.0.1:8765` if the browser does not open automatically.
5. Wait for the header to show `codex.connected` and select a model.
6. Enter the target project path and prompt, then select `analyze()`.
7. Review the original and verified candidate. Submit exactly one route.
8. Answer any command, file-change, or network approval card in the page.
9. The run is finished only when the console shows one of these terminal messages:
   - `[turn/completed: completed]` — successful completion.
   - `[turn/completed: failed; code=…]` — Codex or its transport failed.
   - `[turn/completed: interrupted; code=…]` — the user or safety lifecycle stopped it.

`item/completed` means that one command, file change, or other item finished. It does
not mean that the entire turn finished. The authoritative terminal event is
`turn/completed`, including its status.

### Approvals and stalled runs

SlashToken follows the Codex App Server approval lifecycle: it keeps a request pending
until `serverRequest/resolved` confirms that Codex received or cleared the response.
Buttons are disabled after one response so a request cannot be answered twice.

An unanswered approval displays a countdown and is cancelled after ten minutes. If
Codex does not resolve the cancellation, SlashToken interrupts the turn and eventually
marks an unresponsive App Server as failed. Ordinary model silence is different: after
two minutes the page shows a warning, but it does not automatically cancel healthy
reasoning. See the official [Codex App Server approval protocol](https://learn.chatgpt.com/docs/app-server#command-execution-approvals).

### Reload and reconnect safely

- A browser refresh does not cancel the active turn. The page stores only random
  session, run, and thread identifiers in `sessionStorage`, reconnects, and restores
  buffered activity, current analytics, and any pending approvals.
- Do not stop the `slashtoken ui` terminal if the run is still active. A backend
  restart cannot resume the exact in-flight turn, although persisted status and token
  analytics remain available.
- If every page disconnects for ten minutes, SlashToken interrupts the run to avoid an
  abandoned process. Reopen the same tab before that deadline to reattach.

### Read token analytics

The analytics inspector contains three snapshots:

- **This run** is the component-wise difference between the current thread total and
  the reliable baseline captured before this run.
- **Thread total** is the latest cumulative `tokenUsage.total` reported for the Codex
  thread. Read the newest snapshot; do not add successive socket messages together.
- **Last model call** is `tokenUsage.last`, covering only the most recent model request
  inside the turn.

`total tokens = input tokens + output tokens`. Cached input is already included in
input tokens, and reasoning output is already included in output tokens. They are
subsets for analysis, not extra values to add to the total.

### Timeout configuration

The defaults can be overridden in the SlashToken process environment:

```bash
export SLASHTOKEN_CODEX_APPROVAL_TIMEOUT_SECONDS=600
export SLASHTOKEN_CODEX_DISCONNECT_GRACE_SECONDS=600
export SLASHTOKEN_CODEX_APPROVAL_RESOLUTION_SECONDS=10
export SLASHTOKEN_CODEX_INTERRUPT_TIMEOUT_SECONDS=10
export SLASHTOKEN_CODEX_SILENCE_WARNING_SECONDS=120
```

All values must be greater than zero. Short values are intended only for deterministic
tests; production use should leave enough time to inspect sensitive commands and file
changes.

## MCP server

Register the same installed package:

```bash
codex mcp add slashtoken -- slashtoken mcp
```

Available tools:

- `analyze_prompt`
- `optimize_prompt`
- `run_chat`
- `settings_get`
- `settings_update`
- `usage_summary`

`optimize_prompt` never executes a candidate. It returns a short-lived decision ID.
`run_chat` accepts that decision ID and the approved `candidate` or `original`
selection, so optimized execution cannot skip the preview step. It remains governed
by Codex's MCP approval policy.

## Setting scopes

Settings resolve in this order:

```text
session -> local project -> user defaults
```

Project settings are stored locally by canonical project path. Repository files
cannot grant auto-run consent. User-wide settings cannot enable automatic submission.
