# SlashToken

SlashToken is a local multilingual prompt gateway for Codex and LLM APIs. It
optimizes Chinese, Arabic, and Turkish prompts only when the transformed route can
be verified and is worth using for the selected target model.

The original prompt is captured before Codex sees it. SlashToken protects exact
content, creates and verifies a compact English candidate, displays the routing
evidence, and sends exactly one user-selected prompt onward.

## Product guarantees and boundaries

- Optimization is optional routing, never an unconditional translation step.
- High-stakes prompts are not transformed in v1.
- Names, numbers, URLs, code, quotations, IDs, schemas, negations, and formatting
  constraints receive deterministic preservation checks.
- SlashToken does not claim lossless translation. It reports measured, bounded
  preservation and falls back when checks fail.
- Raw original and transformed prompts are not persisted by the production app.
- Normal usage makes one target-model request. Dual-route comparison is confined to
  explicit benchmark runs.

## Repository map

```text
src/slashtoken/          Production package
  core/                  Provider-independent routing domain
  providers/             Hosted model and tokenizer adapters
  codex/                 Codex App Server client
  mcp/                   Local stdio MCP adapter
  web/                   FastAPI localhost approval client
  settings/              User/project/session configuration
  storage/               Privacy-safe SQLite repositories
benchmarks/              Synthetic multilingual evaluation fixtures
experiments/legacy_tk/   Original isolated Tkinter research harness
tests/                   Unit, integration, and contract tests
docs/                    Architecture, setup, and privacy documentation
```

Production code never imports from `experiments/`.

## Installation

Create a virtual environment and install the package:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[tokenizers,dev]'
```

Set the hosted optimizer credential in your shell or secret manager:

```bash
export NVIDIA_API_KEY="..."
```

SlashToken does not load repository `.env` files in production.

## Commands

Start the local approval client:

```bash
slashtoken ui
```

The browser keeps an active Codex run attached to a server-side session. Reloading
the page reconnects to that run instead of cancelling it. Command and file-change
approvals appear as in-page cards, and the analytics inspector separates this run,
the cumulative thread, and the most recent model call. See
[Codex setup](docs/codex-setup.md) for the exact completion states and recovery flow.

Run the MCP server over stdio:

```bash
slashtoken mcp
```

Run an offline fixture analysis without hosted calls:

```bash
slashtoken benchmark --model gpt-5.6-terra --dry-run
```

Omit `--dry-run` only for an explicit hosted benchmark. That mode executes the
unchanged and optimized target routes separately, runs a structured final-answer
comparison, and reports evaluator usage outside production-route cost.

## Codex MCP registration

After installing SlashToken in the active environment:

```bash
codex mcp add slashtoken -- slashtoken mcp
```

Restart or open a new Codex task after changing MCP configuration. Codex can enable
or disable the server and tools; SlashToken's custom routing toggles live in the web
settings panel and the `settings_get` / `settings_update` MCP tools.

See [Codex setup](docs/codex-setup.md), [architecture](docs/architecture.md),
[privacy](docs/privacy.md), and [project objective](PROJECT_OBJECTIVE.md).

## Development verification

The dependency-free core suite uses the standard library:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

With development dependencies installed:

```bash
pytest
```
