# SlashToken Project Objective and Context

Use this document as the durable source of truth when starting a new ChatGPT or Codex conversation about this project.

## One-sentence objective

Create SlashToken, a multilingual LLM optimization gateway that selects the lowest-cost request path that still meets explicit thresholds for intent preservation, response quality, privacy, and latency.

## The problem

Equivalent ideas can require substantially different token counts across languages and model tokenizers. Since many LLM APIs charge per token, multilingual applications may pay more to serve some users even when their requests contain comparable semantic content.

The opportunity is to determine whether selected requests can be translated or compressed into a more token-efficient representation before being sent to an expensive model, then return the result in the user's desired language. The complete route must be cheaper than sending the original request and must not materially degrade the outcome.

## The product

The intended core product is a provider-facing API gateway with an SDK. It analyzes each request and chooses among routes such as:

- Send the original request unchanged.
- Translate to compact English, verify, then send.
- Use another optimized intermediate representation when evidence supports it.
- Skip optimization for sensitive, ambiguous, unsupported, or uneconomical cases.

A web dashboard supports testing, comparison, and usage reporting. A browser extension may later demonstrate the technology, but it should not define the core architecture.

## Non-negotiable principles

1. **Intent comes before savings.** Names, facts, constraints, tone, formatting, quoted material, code, and requested response language must be preserved.
2. **Savings must be net savings.** Count all translation, verification, model, output, infrastructure, and meaningful latency overhead.
3. **Fallback is a feature.** When confidence or savings is too low, send the original request.
4. **Claims require benchmarks.** Evaluate final answers, not just translated text or token counts.
5. **The system is model-agnostic.** Llama 3.2 can be tested, but translators, tokenizers, and LLM providers must remain replaceable.
6. **Privacy is part of the design.** Minimize retention, avoid logging raw prompts by default, and expose where processing occurs.
7. **No absolute fidelity claims.** The project may measure and bound semantic risk; it cannot promise zero meaning loss.

## Decision function

At a conceptual level, optimize only when:

```text
expected original-path cost
    - expected optimized-path total cost
    >= configured minimum savings

AND

meaning and constraint confidence
    >= configured quality threshold
```

The optimized-path total cost includes translation, verification, target-model input and output, response translation, and relevant infrastructure cost. High-risk content may be excluded regardless of the score.

## Initial hypothesis to test

For a useful subset of Chinese, Arabic, and Turkish prompts sent to a selected paid LLM, a verified intermediate English representation will reduce end-to-end monetary cost enough to justify its compute and latency overhead while preserving final-answer quality within an agreed threshold.

This is a hypothesis, not an established fact. Results may show that only certain languages, prompt lengths, domains, models, or price tiers benefit.

## MVP deliverables

1. A versioned multilingual benchmark with representative prompt categories.
2. Provider-accurate token and price calculation.
3. A pluggable translation and optimization interface.
4. Protected-span handling for entities, numbers, URLs, code, quotations, and formatting constraints.
5. A verification stage and explicit fallback reasons.
6. Original-versus-optimized end-to-end response comparison.
7. API endpoints for analysis, optimization, chat, and aggregate usage.
8. A small dashboard showing tokens, cost, latency, quality signals, routing choice, and net savings.

## Success criteria

Before calling the central hypothesis validated, define numeric targets and demonstrate them on a held-out benchmark. At minimum, evaluate:

- Median and total net cost reduction.
- Percentage of requests safely optimized.
- Semantic and constraint-preservation rate.
- Final-answer quality relative to the original-language baseline.
- False-positive rate: requests optimized when they should not have been.
- Added latency at relevant percentiles.
- Results by language, domain, prompt length, and model.

Exact thresholds should be chosen after baseline data exists. They must not be retrofitted solely to make results look successful.

## Out of scope until the hypothesis is validated

- Promising lossless translation.
- Supporting every language or LLM provider.
- Replacing professional translation in sensitive domains.
- A full standalone consumer or mobile application.
- Large enterprise administration features.
- Browser automation across many third-party AI websites.
- Training a new foundation model.

## Questions that remain open

- Which language, domain, and prompt-length combinations produce reliable net savings?
- Is English consistently the best intermediate language for each target model?
- Which local or hosted translator best balances accuracy, privacy, cost, and latency?
- Which verification method best predicts final-answer degradation?
- When does output cost erase input savings?
- How should code-switching, dialects, slang, and culturally dependent language be routed?
- What privacy model will target customers require?

## Prompt for a future ChatGPT session

Copy the following into a new conversation, then include the relevant repository files or current task:

> We are building the Multilingual Token Cost Optimizer described in `README.md` and governed by `PROJECT_OBJECTIVE.md` and `AGENTS.md`. Treat the main goal as reducing total end-to-end LLM cost only when configured intent-preservation, response-quality, privacy, and latency thresholds are met. Optimization is optional, all overhead must be counted, and uncertain requests must fall back to their original form. Do not assume English or any particular translation model is always best. Review the existing repository state before proposing or making changes, keep the MVP narrowly focused on proving the central hypothesis, and clearly identify any assumptions that lack benchmark evidence.

## Guardrail against objective drift

Before accepting a feature or architecture change, ask:

1. Does it help prove or safely operationalize the core cost-versus-quality hypothesis?
2. Does it measure total cost rather than token reduction in isolation?
3. Does it preserve a reliable original-request fallback?
4. Can its behavior be evaluated reproducibly?
5. Is it necessary for the current milestone?

If most answers are no, defer the work or update this charter explicitly with the reason for changing direction.
