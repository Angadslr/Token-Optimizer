# Privacy and Data Handling

## Hosted processing

SlashToken v1 may send the original prompt to the configured NVIDIA-hosted DeepSeek
provider for transformation and semantic verification. The interface must disclose
that hosted processing before use. High-stakes prompts are not transformed, although
local risk classification still examines their text.

## Local persistence

The SQLite database stores:

- SHA-256 prompt and project identifiers.
- Language, route, and fallback codes.
- Model and tokenizer identifiers.
- Token, cost, and latency measurements.
- Verification, threshold, and approval metadata.
- Codex run, thread, turn, decision, model, lifecycle, and numeric usage metadata.
- Structured Codex failure codes and hashed project identifiers.
- Run liveness diagnostics: the Codex protocol method name of the last observed
  event, its timestamp, a `liveness` label, and a transport health snapshot of
  booleans, counts, and a subprocess return code.

It does not store original prompts, transformed prompts, model answers, commands,
working directories, changed-file paths, approval reasons, or App Server stderr.
The persisted health snapshot deliberately excludes stderr text, file paths, and
prompt content; it records only protocol method names, timestamps, task-state
booleans, and counts.

The browser-reload replay buffer and pending approval details exist only in process
memory while `slashtoken ui` is running. The stderr diagnostic tail is bounded and
process-local; it is neither written to SQLite nor sent to the browser automatically.

Approval candidates remain in an in-process cache for at most 30 minutes and are
removed after execution. Closing the process clears the cache immediately.

## Logging

Application errors report structured failure categories and safe exception types,
not prompt bodies or raw hosted-provider payloads. Temporary provider failures are
classified without exposing upstream response bodies. OpenTelemetry raw-prompt
logging must remain disabled. Synthetic or explicitly authorized benchmark fixtures
are the only prompt content committed to the repository.
