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

### Temporary hosted-provider failures

The NVIDIA-hosted language optimizer automatically retries temporary connection,
timeout, rate-limit, overload, and server failures. If those retries are exhausted,
SlashToken safely bypasses language optimization and presents the unchanged original
prompt for approval instead of reporting an unusable candidate. Nothing is submitted
automatically.

Output optimization is independent of hosted language optimization. If output
optimization is enabled, it still applies when you approve and submit the original
prompt. Authentication failures and malformed provider responses continue to fail
closed rather than being treated as temporary outages.

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
export SLASHTOKEN_CODEX_IDLE_DIAGNOSTIC_SECONDS=300
export SLASHTOKEN_CODEX_STREAM_LIMIT_BYTES=16777216
export SLASHTOKEN_ENGLISH_CONFIDENCE_MARGIN=0.15
export SLASHTOKEN_TRANSFORMATION_MAX_TOKENS=0
export SLASHTOKEN_PROVIDER_TIMEOUT_SECONDS=300
export SLASHTOKEN_PROTECTED_SPAN_SOFT_LIMIT=40
```

All values must be greater than zero. Short values are intended only for deterministic
tests; production use should leave enough time to inspect sensitive commands and file
changes.

`SLASHTOKEN_ENGLISH_CONFIDENCE_MARGIN` is separate from the timeout values. It must be
at least `0` and less than `1`; higher values reject more ambiguous transformed
candidates. Wrong-language candidates are never retried or made approvable.

`SLASHTOKEN_TRANSFORMATION_MAX_TOKENS` controls only the DeepSeek prompt-
transformation completion. Leave it unset or set it to `0`, `none`, `off`, or
`unlimited` to omit the client-side limit. Set a positive integer such as `6000` to
restore a cap. Restart `slashtoken ui` after changing this value.

`SLASHTOKEN_PROVIDER_TIMEOUT_SECONDS` bounds each hosted DeepSeek call
(transformation, verification, chat, and answer evaluation). It must be greater than
zero and defaults to 300. Removing the transformation cap with
`SLASHTOKEN_TRANSFORMATION_MAX_TOKENS=0` avoids truncating long candidates but can
increase latency, so long non-English prompts may need a higher timeout to avoid a
`provider_unavailable` bypass. When retries are exhausted the decision receipt records
the failing stage and a safe cause (an HTTP status such as `HTTP 529`, or
`timeout_or_connection`) without exposing upstream response bodies. Restart
`slashtoken ui` after changing this value.

`SLASHTOKEN_PROTECTED_SPAN_SOFT_LIMIT` caps how many protected spans a prompt may
shield before SlashToken stops protecting low-value kinds. It must be at least `0`
(use `0` to disable trimming) and defaults to 40. Money, IDs, URLs, emails, and code
fences are always protected; once the count exceeds the limit, short quotations and
inline backtick identifiers are left unshielded so the high-value spans still survive
transformation. Over-protection is the most common cause of a `protected_span_mismatch`
rejection on very long prompts: hosted models drop or reorder tokens more often as the
placeholder set grows. On that rejection SlashToken transforms once, retries once, and
if both attempts fail the receipt reports privacy-safe counts (for example
`expected 164, missing 3, reordered; inline_code missing 2`) with no prompt content.
Restart `slashtoken ui` after changing this value.

`SLASHTOKEN_CODEX_STREAM_LIMIT_BYTES` bounds the size of a single App Server stdout
line. Codex file-change notifications can carry large diffs, so this defaults to 16 MiB
rather than Python's 64 KiB stream default. A line larger than the limit fails the
transport with `stdout_line_limit_exceeded` instead of silently killing the reader.

### Run liveness and diagnostics

A run stays `running` while the model is legitimately quiet. After
`SLASHTOKEN_CODEX_IDLE_DIAGNOSTIC_SECONDS` of silence the run manager probes the
transport and reports a separate `liveness` value of `active` or `unresponsive`:

- `unresponsive` means SlashToken has seen no event for the idle window while the
  transport still appears alive. The run is **not** terminated on silence alone; the
  browser surfaces `running · unresponsive` so the condition is visible.
- If the probe finds the stdout reader task dead or the subprocess exited, it wakes
  the blocked consumer and the run finalizes as `failed` with a specific code.

Transport failure codes recorded in `failure_code`:

- `stdout_line_limit_exceeded` — a stdout line exceeded the configured stream limit.
- `stdout_reader_failed` — the stdout reader task raised an unexpected exception.
- `app_server_exited` — the App Server subprocess exited unexpectedly.
- `invalid_json` — the App Server emitted a non-JSON stdout line.
- `backend_shutdown` — the FastAPI application shut down while the run was active; a
  privacy-safe health snapshot is persisted alongside it.

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
