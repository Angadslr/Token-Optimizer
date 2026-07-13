# Multilingual Token Cost Optimizer

An experimental multilingual LLM gateway that aims to reduce API costs while preserving the user's intent.

Many language-model tokenizers represent equivalent content with different numbers of tokens depending on the language. A request written in Chinese, Arabic, Turkish, or another non-English language may therefore cost more to process than an equivalent English request. This project tests whether translating and carefully compressing selected prompts before they reach a paid model can produce meaningful net savings without materially changing their meaning.

## Product concept

The optimizer sits between an application and an LLM provider:

```text
User's original request
        |
        v
Language and token analysis
        |
        v
Optimize only when worthwhile
        |
        v
Meaning and constraint verification
        |
        v
Target LLM provider
        |
        v
Response in the user's requested language
```

The long-term product is an API gateway and SDK. A web dashboard will make the behavior measurable and easy to test. A browser extension may later serve as a demonstration, but it is not the initial core product.

## Core principle

Translation is a routing option, not a requirement.

For every request, the system should compare the expected cost and quality of at least two paths:

1. Send the original request unchanged.
2. Translate or optimize it, verify it, and send the resulting request.

The optimizer should choose the second path only when projected savings exceed all translation and verification overhead and the transformed request passes the configured meaning-preservation threshold. When uncertain, it should use the original request.

## Proposed request pipeline

1. Detect the source language.
2. Count tokens with the tokenizer for the selected target model.
3. Protect names, numbers, URLs, code, quotations, identifiers, and formatting constraints.
4. Produce a compact English candidate when appropriate.
5. Count the candidate's tokens and estimate the complete request cost.
6. Verify semantic equivalence and preserved constraints.
7. Route either the original or optimized request to the target model.
8. Return the answer in the requested language.
9. Record savings, overhead, latency, routing choice, and quality signals without unnecessarily retaining private prompt content.

## MVP scope

The first version should deliberately remain narrow:

- One LLM provider and model.
- A small initial language set, with Chinese, Arabic, and Turkish as useful test candidates.
- A web dashboard for side-by-side experiments.
- A simple API with analysis, optimization, chat, and usage reporting.
- Pluggable translators so the project is not tied to Llama 3.2 or any single model.
- Automatic fallback to the original prompt when savings or confidence is insufficient.

Suggested endpoints:

```text
POST /analyze   Estimate tokens, costs, and the recommended route.
POST /optimize  Return a verified optimization candidate without calling the final model.
POST /chat      Run the complete routing and response pipeline.
GET  /usage     Report aggregate tokens, costs, latency, and routing outcomes.
```

## What must be measured

This project succeeds through evidence, not through token-count reduction alone. Evaluation should include:

- Original versus optimized input tokens using the target model's actual tokenizer.
- Translation and verification overhead.
- Net monetary savings based on current provider pricing.
- Intent, entities, constraints, tone, and requested-output preservation.
- Final-answer quality compared with sending the original prompt.
- End-to-end latency.
- Optimization acceptance and fallback rates by language and use case.
- Privacy and data-retention behavior.

The primary experiment should use a representative multilingual prompt set and compare both routes end to end. Token savings that produce lower-quality answers do not count as success.

## Important limitations

- No translation system can guarantee that meaning is never lost.
- English is not always the cheapest or best intermediate representation.
- Short requests may not save enough to justify added work.
- Output tokens can dominate total cost when a long response must be returned in the original language.
- Legal, medical, financial, safety-critical, literary, and highly culture-dependent text may require stricter rules or no optimization.
- Provider prices, tokenizers, and model capabilities change, so routing inputs must be configurable.

The product should make bounded, testable claims such as “reduces measured multilingual LLM cost under configured quality thresholds,” not “zero meaning loss.”

## Possible implementation direction

The architecture is intentionally undecided until experiments justify it. A practical prototype could use:

- React or Next.js for the testing dashboard.
- Python and FastAPI for the gateway.
- Provider-specific token counting.
- A local or hosted multilingual translation model behind a common interface.
- PostgreSQL or another relational store for aggregate usage and experiment results.

These are starting points, not permanent requirements.

## Repository status

This repository is at the research and product-definition stage. The next milestone is a reproducible benchmark that establishes where optimization saves money, where it harms quality, and where the original-language route should win.

See [PROJECT_OBJECTIVE.md](PROJECT_OBJECTIVE.md) for the durable product charter and [AGENTS.md](AGENTS.md) for repository working rules.

