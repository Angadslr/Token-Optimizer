# AGENTS.md

This file contains working instructions for AI coding agents and human contributors in this repository. It applies to the entire repository unless a more specific `AGENTS.md` exists in a subdirectory.

## Start here

Before making a significant change:

1. Read `README.md` for the product overview.
2. Read `PROJECT_OBJECTIVE.md` for the durable objective, boundaries, and decision rules.
3. Inspect the current code and tests rather than assuming the proposed stack has already been adopted.
4. Preserve unrelated user changes and never overwrite secrets or local configuration.

## Main objective

Build an evidence-driven multilingual LLM gateway that reduces total API cost when it can do so without violating configured intent-preservation and quality thresholds.

The goal is not translation for its own sake and not minimizing token count at any cost. The system must account for the full request path, including translation, verification, model input, model output, response translation, latency, and quality.

## Product priorities

When choices conflict, prefer them in this order:

1. Preserve user intent, entities, constraints, and requested output behavior.
2. Protect user data and make data handling explicit.
3. Measure real end-to-end cost with the selected provider and model.
4. Fall back safely to the original request when confidence is insufficient.
5. Keep routing decisions observable and reproducible.
6. Improve latency, convenience, and breadth of integrations.

## Required behavior

- Treat optimization as optional routing. Never assume every non-English request should be translated.
- Compare the original and optimized paths using provider-specific tokenization and pricing.
- Include translation and verification overhead in savings calculations.
- Preserve protected spans such as names, numbers, URLs, code, quotations, IDs, and explicit formatting requirements.
- Make confidence thresholds and minimum-savings thresholds configurable.
- Use the original prompt when a check fails, a language is unsupported, or projected net savings are inadequate.
- Keep translator and provider implementations behind clear interfaces so individual models can be replaced.
- Record why a routing decision was made without logging sensitive prompt content by default.
- Do not claim “no meaning loss.” Describe quality in measured, bounded terms.

## Evaluation rules

Every optimization change should be evaluated against an unchanged-original baseline. Where applicable, report:

- Input and output token counts.
- Translation and verification token or compute costs.
- Estimated or actual monetary cost.
- End-to-end latency.
- Semantic and constraint-preservation results.
- Final-answer quality.
- Route selected and fallback reason.
- Results broken down by language and prompt category.

Do not accept an optimization solely because it lowers the English prompt's token count. It must improve the configured end-to-end objective.

## Development practices

- Favor small, testable modules over a tightly coupled pipeline.
- Keep pricing, model names, tokenizer selection, thresholds, and language support in configuration.
- Use deterministic fixtures where possible; version benchmark datasets and evaluation prompts.
- Add tests for successful optimization, no-savings fallback, failed verification, protected-span preservation, unsupported languages, and provider errors.
- Avoid silently changing public API response shapes.
- Document assumptions and tradeoffs near the code or decision they affect.
- Do not commit `.env` files, API keys, raw private prompts, or customer data.
- Use synthetic or explicitly authorized text in tests and examples.

## Scope control

The near-term scope is a benchmark, a small gateway API, and a testing dashboard. Avoid building a mobile app, broad enterprise platform, or fragile site-specific browser automation before the core cost-and-quality hypothesis is demonstrated.

New work should answer at least one of these questions:

- Does this improve measurement reliability?
- Does this reduce net cost while meeting quality thresholds?
- Does this make unsafe transformations easier to detect or avoid?
- Does this help developers integrate or understand the optimizer?

If not, explain why the work belongs in the current milestone before implementing it.

## Definition of done

A change is complete when it is implemented, relevant tests pass, documentation or configuration is updated, and its impact on cost, quality, privacy, or fallback behavior is understood. Experimental results should be reproducible from documented inputs and settings.

