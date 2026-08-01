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
5. Transform into compact English while preserving response-language instructions.
6. Count original and candidate tokens for the selected target model.
7. Reject candidates that do not save tokens.
8. Compare protected spans character-for-character.
9. Run one structured semantic verifier.
10. Return a decision receipt and wait for approval.

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
