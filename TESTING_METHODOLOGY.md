# SlashToken Testing Methodology

## Purpose

This document defines a reproducible method for determining whether multilingual
prompt optimization reduces total LLM cost without violating configured intent,
constraint, answer-quality, privacy, or latency requirements.

The central question is not whether an English prompt contains fewer tokens. The
central question is whether an optimized route produces a satisfactory final answer
at a lower end-to-end cost than sending the original request unchanged.

No result from this benchmark should be described as proving that translation is
lossless. The benchmark measures bounded preservation and quality under documented
conditions.

## Routes to compare

Every test case must be evaluated against an unchanged-original baseline.

### Route A: Original-language baseline

```text
Original prompt
    -> main model
    -> answer in requested language
```

This is the control route. It must use the user's original prompt exactly as supplied.

### Route B: Input optimization only

```text
Original prompt
    -> English translation or compact English prompt
    -> verification
    -> main model
    -> answer directly in requested language
```

This route tests whether main-model input cost can be reduced without adding response
translation.

### Route C: Input and output optimization

```text
Original prompt
    -> compact English prompt
    -> prompt verification
    -> main model produces compact English answer
    -> answer translated into requested language
    -> response verification
    -> final answer
```

This route can reduce both main-model input and output cost, but it introduces an
additional response-translation quality risk.

### Route D: Compact original language

```text
Original prompt
    -> compact prompt in original language
    -> verification
    -> main model
    -> answer in requested language
```

This route separates the effect of compression from the effect of translation.

## Important distinction: prompt variants versus final answers

A prompt-transformation screen and an end-to-end answer-comparison screen measure
different things.

- A **prompt variant** is a rewritten request intended to be sent to the main model.
- A **final answer** is the main model's response after it receives one of those
  variants.

An `English translation` or `Compressed English` prompt panel should display an
English version of the user's complete request. It should not answer the request.
If that panel instead displays a Chinese JSON answer, record a **transformation
instruction-following failure**. Do not treat that output as a successful compressed
English variant.

## Experimental controls

For a fair comparison, keep the following constant across routes unless the tested
route explicitly requires a different component:

- Main-model provider and model version.
- Provider endpoint and API settings.
- Temperature, sampling parameters, and maximum output limit.
- System/developer instructions used for final-answer generation.
- Requested response format and language.
- Pricing snapshot and currency.
- Test machine and local-model configuration.
- Network location where practical.
- Retry policy and timeout settings.

Record all of these with the results. Use temperature `0` for the first deterministic
benchmark, while recognizing that provider behavior may still vary.

## Trace every request

Assign a unique `trace_id` to every route execution. Record each stage separately
rather than storing only one combined token or cost total.

Each trace should answer:

1. What went into each stage?
2. What came out of each stage?
3. Which provider and model performed it?
4. How many tokens or how much local compute did it use?
5. How long did it take?
6. How much did it cost?
7. Which validation checks passed or failed?
8. Why was the route selected or rejected?

Avoid retaining raw private prompts by default. Benchmark fixtures should be synthetic
or explicitly authorized. Store hashes, fixture identifiers, aggregate measurements,
and failure metadata where raw text is unnecessary.

## Measurements

### 1. Token usage

Prefer the actual usage reported by the provider after the request. Estimates from a
local tokenizer are useful before routing but should not replace billed usage in the
final evaluation.

Record input, cached input, and output tokens separately for:

- Prompt translation or compression.
- Prompt verification.
- Main-model generation.
- Response translation.
- Response verification.
- Format repair or retries.

For local models, use the tokenizer belonging to the exact deployed model and record
both input and output tokens.

Example stage ledger:

| Stage | Model | Input tokens | Cached input | Output tokens |
|---|---|---:|---:|---:|
| Prompt transformation | translator | 0 | 0 | 0 |
| Prompt verification | verifier | 0 | 0 | 0 |
| Main generation | target model | 0 | 0 | 0 |
| Response translation | translator | 0 | 0 | 0 |
| Response verification | verifier | 0 | 0 | 0 |

### 2. Monetary cost

Keep model names and prices in versioned configuration. Save the date of the pricing
snapshot because provider prices can change.

For each API call:

```text
input_cost = input_tokens / 1,000,000 * input_price_per_million
cached_input_cost = cached_input_tokens / 1,000,000 * cached_input_price_per_million
output_cost = output_tokens / 1,000,000 * output_price_per_million

call_cost = input_cost + cached_input_cost + output_cost
```

Calculate the optimized route's total rather than looking only at the main-model call:

```text
optimized_route_cost =
    prompt_transformation_cost
    + prompt_verification_cost
    + main_model_cost
    + response_translation_cost
    + response_verification_cost
    + repair_and_retry_cost
    + estimated_infrastructure_cost
```

Then compare it with the baseline:

```text
net_savings = baseline_total_cost - optimized_route_total_cost

net_savings_percent =
    net_savings / baseline_total_cost * 100
```

A negative result means the optimized route cost more than the baseline.

### 3. Local compute cost

A local translation model has no per-request API charge, but it consumes hardware,
energy, and time. At minimum, record:

- Machine or accelerator type.
- Model name, revision, and quantization.
- Input and output tokens.
- Processing duration.
- Peak memory if available.
- Estimated machine cost per hour.

Estimate cost as:

```text
local_compute_cost =
    processing_seconds / 3,600 * estimated_machine_cost_per_hour
```

Label this as an estimate and report it separately from billed API cost.

### 4. Latency

Use a monotonic high-resolution timer around every stage and around the entire route.
In Python, `time.perf_counter()` is appropriate.

Record:

- Language detection latency.
- Protected-span extraction latency.
- Prompt transformation latency.
- Prompt verification latency.
- Main-model latency.
- Response translation latency.
- Response verification latency.
- Repair and retry latency.
- Total wall-clock latency.

Measure total wall-clock time directly. Do not rely only on the sum of provider
measurements because queuing, networking, and local orchestration also affect users.

If independent stages run concurrently, their individual durations will not sum to
the end-to-end duration.

### 5. Protected-span preservation

Each fixture should declare exact protected values, such as:

- Names and organizations.
- IDs and product codes.
- Numbers, dates, times, ranges, units, and currencies.
- URLs and email addresses.
- Code, function names, and literal values.
- Quotations and citations.
- Required field names and formatting markers.

Compare required values character-for-character at every stage where they should
appear.

```text
protected_span_accuracy =
    correctly_preserved_required_spans / total_required_spans * 100
```

Store the result for every span, not only the aggregate percentage. A changed
currency amount or reversed boolean can be a critical failure even when the aggregate
score is high.

### 6. Constraint preservation

Turn every testable user instruction into an explicit assertion. Example assertions
for the structured Chinese test fixture include:

- Output parses as valid JSON.
- Only the specified top-level keys appear, if exact keys are required.
- `reasons` contains exactly three items.
- Ranks are `1`, `2`, and `3`.
- `before_release_actions` contains exactly two items.
- Exactly one post-release action is returned.
- `decision` contains one of the allowed values.
- The final answer is in Simplified Chinese.
- No Markdown code fence surrounds the JSON.
- Required protected values are unchanged.
- No claim of actual patient harm is introduced.
- No medical advice is introduced.

Calculate a general constraint score:

```text
constraint_accuracy = passed_assertions / total_assertions * 100
```

Also designate critical assertions. A route must fail regardless of its aggregate
score if it reverses a negation, changes a material number, violates a safety
condition, or returns an unusable format.

### 7. JSON and structured-output validity

Attempt to parse the raw output directly with a standard JSON parser.

Record:

- `json_valid`: true or false.
- Parse error text and location.
- Missing or unexpected keys.
- Incorrect value types.
- Schema-validation result.
- Whether a repair was attempted.
- Repair tokens, cost, latency, and outcome.

Do not silently score repaired JSON as an initially valid response.

### 8. Semantic and intent preservation

Lexical overlap is not a reliable semantic metric. Use a fixture-specific proposition
checklist that captures the facts and distinctions that must survive.

For the Chinese release-incident fixture, check whether the transformed prompt and
final response preserve that:

- The release date and time are unchanged.
- Only 68% of testing is complete.
- Performance degradation is possible, not confirmed.
- Li Wen's no-release condition remains mandatory.
- Empty patient IDs are incorrectly accepted.
- All financial values remain estimates and are unchanged.
- Repair and retesting require 14–22 hours.
- No real patient harm is claimed.
- The requested decision, reasons, and actions remain required.
- Negations such as “must not release” and “cannot conclude” are not reversed or
  weakened.

Score each proposition:

```text
2 = fully preserved
1 = partially preserved or ambiguous
0 = missing, contradicted, or materially changed
```

```text
semantic_preservation_score =
    earned_points / maximum_points * 100
```

Use three complementary evaluation layers:

1. Deterministic checks for exact values, counts, schemas, and keywords.
2. A separate evaluator model using a fixed, versioned rubric.
3. Blind human review of a representative sample.

Back-translation can provide an additional signal but must not be treated as proof of
equivalence. Related models can reproduce or overlook the same error in both
directions.

### 9. Final-answer quality

Evaluate final answers separately from transformed prompts. A prompt can be faithfully
translated yet produce a worse answer, and a flawed transformation can occasionally
produce a plausible answer by chance.

Blind evaluators to route identity and score each final answer from 1 to 5 on:

- Factual correctness.
- Completeness.
- Reasoning quality.
- Instruction following.
- Appropriate uncertainty and qualifications.
- Fluency and naturalness in the requested language.
- Formatting usability.

Retain every dimension as well as the average. Define an allowed quality delta from
the baseline before examining optimized results.

### 10. Transformation success

Before sending a transformed prompt to the main model, validate that it is actually a
prompt rather than an answer.

For an English transformation route, check this regardless of the source language or
writing system:

- The result is predominantly English, excluding protected spans.
- It retains the user's task as instructions rather than completing the task.
- It contains the required response-language instruction.
- It retains the requested output schema as an instruction.
- It has not filled the requested schema with a substantive answer.
- It contains no unsupported conclusions.

For original-language compression, verify that the candidate remains in the detected
source language. Do not infer language solely from a hard-coded list of scripts:
Latin script, for example, is shared by English, Spanish, French, Turkish, and many
other languages. Use a language-aware detector or a structured verification stage,
and record uncertain or unsupported language identification as a fallback.

Suggested status values:

```text
success
wrong_language
answered_instead_of_transformed
constraint_loss
protected_span_failure
empty_output
provider_error
```

An `answered_instead_of_transformed` result must be rejected before routing. It is not
a usable English candidate, regardless of its apparent answer quality.

### 11. Retries and failure cost

Every retry consumes time and may consume tokens. Record:

- Stage that failed.
- Failure reason.
- Retry count.
- Tokens and cost per failed attempt.
- Backoff delay.
- Final outcome.
- Whether the system fell back to the original route.

Include all failed calls in total route cost. Otherwise the benchmark will overstate
savings.

### 12. Routing outcome and fallback reason

Record the final route and a machine-readable reason, for example:

```text
optimized
no_projected_savings
quality_below_threshold
transformation_failed
verification_failed
protected_span_failure
unsupported_language
high_risk_content
provider_error
```

The safest behavior after a failed transformation or verification is to use the
unchanged original prompt, subject to the normal provider-error policy.

## Example trace record

```json
{
  "trace_id": "zh-release-001-route-c-run-01",
  "fixture_id": "zh-release-001",
  "route": "input_and_output_optimized",
  "source_language": "zh-CN",
  "requested_output_language": "zh-CN",
  "settings": {
    "main_model": "provider/model-version",
    "translator": "provider-or-local/model-version",
    "verifier": "provider/model-version",
    "temperature": 0,
    "max_output_tokens": 2500,
    "pricing_snapshot": "YYYY-MM-DD"
  },
  "usage": {
    "prompt_transformation_input_tokens": 0,
    "prompt_transformation_output_tokens": 0,
    "prompt_verification_input_tokens": 0,
    "prompt_verification_output_tokens": 0,
    "main_input_tokens": 0,
    "main_cached_input_tokens": 0,
    "main_output_tokens": 0,
    "response_translation_input_tokens": 0,
    "response_translation_output_tokens": 0,
    "response_verification_input_tokens": 0,
    "response_verification_output_tokens": 0
  },
  "latency_ms": {
    "prompt_transformation": 0,
    "prompt_verification": 0,
    "main_generation": 0,
    "response_translation": 0,
    "response_verification": 0,
    "total": 0
  },
  "cost_usd": {
    "prompt_transformation": 0,
    "prompt_verification": 0,
    "main_model": 0,
    "response_translation": 0,
    "response_verification": 0,
    "retries": 0,
    "local_compute_estimate": 0,
    "total": 0
  },
  "evaluation": {
    "transformation_status": "success",
    "protected_spans_correct": 0,
    "protected_spans_required": 0,
    "constraints_passed": 0,
    "constraints_total": 0,
    "json_valid": false,
    "semantic_preservation_score": 0,
    "answer_quality_dimensions": {
      "correctness": 0,
      "completeness": 0,
      "reasoning": 0,
      "instruction_following": 0,
      "uncertainty": 0,
      "language_fluency": 0,
      "formatting": 0
    },
    "critical_failure": false,
    "failure_reasons": []
  },
  "routing": {
    "selected_route": "original",
    "reason": "verification_failed"
  }
}
```

## Test execution procedure

### Phase 1: Validate transformation stages

Before testing final answers:

1. Submit every fixture to each transformation route, across all languages currently
   claimed as supported by the selected translator and verifier.
2. Confirm that translation routes produce the intended intermediate language.
3. Confirm that transformers rewrite the request rather than answer it.
4. Run protected-span and constraint checks.
5. Reject invalid candidates and record fallback reasons.

This phase prevents a fluent but invalid transformation from contaminating the
end-to-end comparison.

### Phase 2: Run the unchanged baseline

1. Send the original prompt unchanged to the main model.
2. Capture raw usage, latency, cost, and output.
3. Validate the response format and constraints.
4. Score semantics and final-answer quality.

### Phase 3: Run optimized routes

1. Generate and validate the route's prompt candidate.
2. If validation fails, record the failure and exercise the original fallback.
3. If validation passes, send the candidate to the same main model.
4. For Route C, translate and verify the response.
5. Capture all stage usage, latency, cost, and outputs.
6. Apply the same final-answer rubric used for the baseline.

### Phase 4: Compare results

For each optimized route, calculate:

- Absolute and percentage net savings.
- Quality delta from the baseline.
- Added latency.
- Protected-span accuracy.
- Constraint-preservation rate.
- Transformation failure rate.
- Verification failure rate.
- Fallback rate.
- Critical-failure rate.

Do not average away critical failures. Report their count and nature separately.

## Repetition and dataset design

A single prompt and a single run cannot validate the product. Start with at least 10
runs per route for pipeline debugging, then expand to a versioned dataset across:

- Chinese, Arabic, Turkish, and the unchanged English control.
- Short, medium, and long prompts.
- Extraction, classification, summarization, reasoning, structured output, customer
  support, and code-related tasks.
- Prompts with protected entities, numbers, URLs, quotations, and code.
- Ambiguous instructions, negations, uncertainty, and code-switching.
- Low-risk and deliberately excluded high-risk categories.

Split fixtures into development and held-out evaluation sets. Do not adjust thresholds
only to improve held-out results.

Report the mean, median, relevant percentiles, worst cases, and failure rate. Break
results down by language, task category, prompt length, route, and model.

## Route acceptance rule

Choose thresholds before evaluating the held-out benchmark. Conceptually, accept an
optimized route only when:

```text
projected_net_savings >= configured_minimum_savings
AND semantic_preservation_score >= configured_semantic_threshold
AND final_answer_quality >= configured_quality_threshold
AND no_critical_failure
AND latency <= configured_latency_limit
```

If a check fails, use the unchanged original route and record the reason.

Token reduction by itself is never sufficient evidence of success.

## Interpreting the observed Chinese JSON in “Compressed English”

If the `Compressed English` panel returns a completed Chinese JSON answer, classify
the run as:

```text
transformation_status = answered_instead_of_transformed
candidate_language = zh-CN
candidate_valid_for_route = false
fallback_reason = transformation_failed
```

The JSON may be a reasonable answer to the original task, but it is not a compact
English prompt. It therefore provides no evidence about English input-token savings
and must not be sent onward as though it were the transformed request.

The current fixture contains strong embedded instructions to return Simplified Chinese
and output only JSON. Those instructions must remain inside the English prompt as
requirements for the eventual main model; the transformation model must not execute
them. A robust pipeline needs explicit post-transformation validation because a model
can still answer the embedded task despite being instructed only to transform it.

## Minimum report

Every experiment summary should contain:

- Models, versions, settings, and pricing date.
- Fixture set and number of runs.
- Baseline and optimized input/output tokens.
- Translation, verification, retry, and infrastructure overhead.
- Total monetary cost and net savings.
- End-to-end latency and stage latency.
- Protected-span and constraint results.
- Semantic-preservation and final-answer-quality results.
- Transformation, verification, and critical-failure rates.
- Selected routes and fallback reasons.
- Results broken down by language and prompt category.

A useful conclusion has the form:

```text
For the evaluated model, language, and task category, Route B reduced median
end-to-end cost by X% while remaining within the predefined quality threshold.
Y% of requests were rejected or fell back, and Z critical failures occurred.
```

Avoid conclusions based only on the number of tokens in an English intermediate
prompt.

## Opt-in NVIDIA translation smoke test

The live integration test uses the synthetic Chinese coding fixture and the same
`/api/optimize` endpoint as the browser. It performs prompt transformation and
semantic verification only; it does not call Codex or generate a target-model answer.
It is skipped during ordinary test runs so CI and local development never spend API
credits implicitly.

```bash
SLASHTOKEN_RUN_LIVE_TESTS=1 \
  python -m unittest tests.integration.test_live_nvidia_translation -v
```

The test requires `NVIDIA_API_KEY`, prints the accepted English candidate and
privacy-safe measurements, and fails if language, protected spans, prompt behavior,
verification, or target-input token savings do not satisfy the route contract.
