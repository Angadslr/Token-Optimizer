# SlashToken Architecture

## Why the pre-Codex client exists

An MCP tool called by Codex cannot reduce the input tokens of the user message that
caused the tool call; that message is already in model-visible context. SlashToken's
localhost client therefore owns the pre-send composer. It submits only the approved
original or approved candidate through Codex App Server.

```text
Browser composer
  -> shared optimization pipeline
  -> in-memory approval cache
  -> selected prompt only
  -> Codex App Server or explicit chatbot provider
```

## Dependency direction

```text
web / MCP / CLI / benchmarks
          |
          v
    settings + core
          |
          v
 providers + storage
```

The domain package has no dependency on FastAPI, MCP, Codex, Tkinter, or SQLite.
Adapters compose it at process startup. The legacy experiment is outside this graph.

## Routing sequence

1. Validate input and identify the source language.
2. Classify explicit high-stakes categories.
3. Extract protected spans locally.
4. Bypass unsupported, high-stakes, or very short requests.
5. Replace protected values with collision-resistant opaque placeholders.
6. Transform the shielded prompt into compact English while preserving every
   placeholder exactly once and in source order.
7. Validate placeholder identity, count, and order, then restore the exact protected
   values locally.
8. Compare restored protected spans character-for-character, including duplicate
   occurrence counts.
9. Count original and candidate tokens for the selected target model and reject
   candidates that do not save enough.
10. Run one structured semantic verifier.
11. Return a decision receipt and wait for approval.

The transformer never regenerates protected values. A missing, duplicated, changed,
or reordered placeholder rejects the candidate; SlashToken does not guess where the
source content belongs. Restoring exact content may remove the projected savings, in
which case the original route remains the correct result.

Auto-run additionally requires an exact tokenizer, a calibrated language/model
threshold, a verified candidate, and session or local-project consent.

Hosted optimizer prices are configuration, not hard-coded facts. Cost fields are
marked unavailable until both per-million input and output prices are supplied.

Calibrated thresholds are loaded from the explicit `SLASHTOKEN_THRESHOLDS_PATH` JSON
file. It contains a `thresholds` array with `language`, `model`,
`minimum_tokens_saved`, `minimum_percent_saved`, `calibrated`, and `version` fields.
SlashToken ships without calibrated defaults, so preview remains the initial route.

## Output optimization

SlashToken does not rewrite completed answers. When enabled, the Codex bridge applies
`model_verbosity = "low"` and a short workload-specific developer policy during
thread start or resume. This removes unnecessary narration without imposing a hard
token cap or reducing requested implementation and explanation quality.

## Codex transport and run liveness

Codex App Server events flow over line-delimited JSON on the subprocess stdout:

```text
codex app-server stdout
  -> CodexAppServerClient._read_stdout -> _dispatch
  -> notifications asyncio.Queue
  -> CodexSession.events
  -> CodexRunManager._execute -> _handle_event
  -> per-browser subscriber queue -> /ws/codex
```

The reader is supervised. `_read_stdout` routes every non-cancellation exit through
`_fail_transport`, which places a `CodexAppServerError` on the notification queue and
fails all pending JSON-RPC futures. This prevents a dead reader from leaving the run
manager blocked forever on an empty queue. The subprocess is launched with an explicit
stream limit (default 16 MiB) so a large file-change line is delivered rather than
raising the 64 KiB `readline` limit error; a line beyond the configured limit fails
the transport explicitly with `stdout_line_limit_exceeded`. The stderr drain is
similarly guarded but never fails the transport, since stderr is diagnostics only.

Because a legitimately busy model can be quiet for minutes, silence alone never
terminates a run. A per-run liveness watcher wakes after
`SLASHTOKEN_CODEX_IDLE_DIAGNOSTIC_SECONDS` of no events and takes a privacy-safe
health snapshot. If the transport is alive it records `liveness = unresponsive` and
leaves the run `running`; if the reader task is dead or the subprocess has exited it
calls `check_liveness`, which drives the same failure path so the run reaches a
terminal state instead of hanging. The last event method, its timestamp, the liveness
label, and the health snapshot are persisted so a stalled run can be diagnosed after a
backend restart.
