# Foundry Prompt, Schema, and Evaluation Guidance

## 1. Purpose and safety boundary

The Nurse Intake Assistant evaluation system measures deterministic application-contract behavior with repository-owned, fictional intake data. It is an offline development and portfolio aid. It does not establish clinical correctness, production readiness, hosted managed-identity execution, live-provider quality, patient-safety certification, or autonomous medical decision-making.

Every extraction and urgency result is advisory. Human nurse review remains mandatory before clinical action. The evaluation is fictional-data-only, exact-match and deterministic, and provider-neutral at the evaluator boundary. It is not clinical validation, not model-as-judge evaluation, not a live Foundry evaluation, and not a provider comparison or ranking.

## 2. Evaluation execution modes

The existing application evaluation supports two independently selected modes:

- `structured-extraction` exercises the real `FoundryAiService` application path with an injected deterministic fake inference client.
- `agent` exercises the real `FoundryNurseIntakeAgent` path with an injected deterministic fake Agent client, including malformed-output fallback evidence.

One CLI execution selects exactly one mode and invokes the application-composed runner once. The runner uses production application composition through `compose_application(settings)`, processes the complete dataset through `CaseProcessingService`, adapts application-owned results, and calls the evaluator after the candidate mapping is complete. There is no combined mode, winner calculation, provider ranking, or cross-mode report.

## 3. Prompt and instruction ownership

Prompt and instruction ownership is separate from application-owned validation:

- [`src/app/services/foundry_extraction_contract.py`](../src/app/services/foundry_extraction_contract.py) owns `build_foundry_structured_extraction_prompt`, the structured-extraction response shape, parsing, and safe normalization metadata. [`src/app/services/foundry_ai_service.py`](../src/app/services/foundry_ai_service.py) sends that prompt through its injected client seam and returns application models.
- [`src/app/services/nurse_intake_agent_instructions.py`](../src/app/services/nurse_intake_agent_instructions.py) owns the centralized Foundry Agent instructions, instruction version, safety rules, and expected Agent JSON shape.
- [`src/app/services/foundry_agent_contract.py`](../src/app/services/foundry_agent_contract.py) owns strict parsing of the raw Agent response into application models.
- [`src/app/services/nurse_intake_agent_contract.py`](../src/app/services/nurse_intake_agent_contract.py) validates the result exposed by a `NurseIntakeAgent`. [`src/app/services/case_processing_service.py`](../src/app/services/case_processing_service.py) owns safe fallback, deterministic urgency-rule merging, persistence orchestration, notification suppression, and pending nurse review.

Prompts and Agent instructions influence provider behavior. Application-owned schemas determine whether returned output may be trusted. Production application composition selects the real service path; deterministic evaluation measures only the resulting canonical evidence. The source files above remain authoritative, so this guide summarizes rather than copying their prompt bodies.

## 4. Application-owned schemas

The schema boundaries form a deliberate chain:

1. Provider response parsers reject malformed structured-extraction or Agent content and normalize accepted content into `ExtractionSummaryResult` and `UrgencyClassificationResult`.
2. `CaseProcessingService` builds a `CaseDocument`, always applies deterministic red-flag rules, preserves pending nurse review, and supplies safe Agent fallback when validation or execution fails.
3. [`src/app/services/foundry_evaluation_adapters.py`](../src/app/services/foundry_evaluation_adapters.py) verifies processing-trace, urgency-merge, intake-state, and fallback evidence before adapting a `CaseDocument`.
4. [`src/app/services/foundry_evaluation.py`](../src/app/services/foundry_evaluation.py) strictly validates the provider-neutral `EvaluationCandidate`, expected-case labels, per-case results, aggregate metrics, and sanitized report.
5. [`src/app/services/foundry_application_evaluation.py`](../src/app/services/foundry_application_evaluation.py) owns production composition, complete dataset processing, exact dataset-ID candidate keys, adapter selection, and the single evaluator call.

Expected urgency labels remain `Routine` or `Urgent`. Contract-valid observed urgency is also binary. Contract-invalid observed application output may use application-consistent `Unknown`: a Routine deterministic rule leaves final urgency `Unknown`, while an Urgent rule promotes final urgency to `Urgent`. `Unknown` scores as an ordinary advisory and final urgency mismatch rather than aborting the run. Deterministic-rule agreement and mandatory nurse-review evidence remain independently scoreable.

The evaluator does not silently coerce malformed output or fabricate valid binary urgency. Contradictory evidence fails closed before scoring.

## 5. Dataset and fixture roles

The evaluation inputs have distinct purposes:

- [`evaluation/fictional-intake-baseline-v1.json`](../evaluation/fictional-intake-baseline-v1.json) is the repository-owned expected dataset: eight fictional cases, stable case IDs, binary expected urgency and rule labels, structured fields, symptoms, missing fields, and mandatory nurse review.
- `scripts/evaluate_foundry_application.py` derives deterministic fake-client responses from that dataset. Each intake still crosses normal application composition and processing. Agent mode deliberately returns a malformed response for `invalid-candidate-output`, so real Agent parsing and application fallback create the invalid canonical candidate.
- [`evaluation/fictional-intake-baseline-v1-candidates.json`](../evaluation/fictional-intake-baseline-v1-candidates.json) is a separate, intentionally imperfect candidate fixture used by the fixture-based baseline CLI. Its extraction, negation, collection, missing-field, urgency, and invalid-contract imperfections are deliberate regression evidence.
- Per-case results hold safe counts, match booleans, contract validity, and an allowlisted error category. Aggregate results sum those observations into deterministic counts and rates.

Fixture imperfections must not be “fixed” merely to improve scores. An intentional behavior change needs a frozen hypothesis and evidence; changing expected labels solely to hide regressions invalidates the comparison.

## 6. Metrics and interpretation

The evaluator implements these metrics without weights or subjective judgment:

- Contract validity count and rate.
- Structured-field exact matches and rate across patient name, date of birth, callback identifier, and reason for calling. Values are trimmed, then compared exactly.
- Symptom precision, recall, and F1 using case-insensitive, trimmed set membership.
- Missing-field recall using the same normalized set behavior, with false-positive and false-negative counts retained in the report.
- Advisory urgency accuracy.
- Final urgency accuracy after deterministic application merging.
- Deterministic-rule agreement.
- Mandatory nurse-review invariant count and rate.

Invalid candidates are isolated per case: they do not abort the dataset, and invalid structured/symptom/missing evidence receives no fabricated credit. Safe urgency, rule, and nurse-review evidence remains independently comparable when the contract-invalid candidate itself is valid.

Every zero denominator produces the deterministic `0.0` value. Cases are ordered by case ID. Aggregate output is sanitized and deterministic: it contains no intake text, prompt, raw provider response, endpoint, credential, generated repository ID, or timestamp. Exact-match means there is no semantic similarity, weighted score, pass threshold, model-as-judge grade, or clinical-quality claim.

## 7. Running the existing CLI

The existing CLI requires one explicit `--mode`; this workflow selects its optional `--json` output. It reads the repository dataset, creates deterministic offline fake clients and settings, and writes no report file. Run it from the repository root; no environment file or live setting is needed.

Structured extraction:

```bash
set -o pipefail
.venv/bin/python scripts/evaluate_foundry_application.py --mode structured-extraction --json | .venv/bin/python -m json.tool
```

Agent:

```bash
set -o pipefail
.venv/bin/python scripts/evaluate_foundry_application.py --mode agent --json | .venv/bin/python -m json.tool
```

Each raw CLI execution emits one newline-terminated JSON document and creates no repository report artifact. With unchanged repository inputs, repeated runs of the same mode are expected to be byte-identical before pretty-printing. Pretty-printing changes presentation only.

## 8. Safe prompt or schema iteration

Use one narrow hypothesis at a time:

```text
freeze one prompt or schema hypothesis
-> update the authoritative prompt/schema source
-> update focused contract tests when behavior intentionally changes
-> run exactly one evaluation mode
-> inspect deterministic per-case and aggregate changes
-> preserve safety rules and nurse review
-> review independently
```

A future prompt or schema change must not simultaneously:

- Change metrics, weights, thresholds, ordering, or serialization.
- Change the fictional expected dataset solely to hide regressions.
- Compare or rank providers or add a combined mode.
- Introduce live evaluation or model-as-judge scoring.
- Change deterministic urgency rules.
- Weaken safe fallback or nurse review.

Those responsibilities require separately frozen slices. Keep prompt changes in the structured-extraction prompt owner, instruction changes in the Agent instruction owner, and intentional schema changes in the application contract that owns them.

## 9. Current limitations and deferred work

The current evaluation has:

- No live evaluation or provider ranking.
- No hosted managed-identity proof.
- No clinical validation, patient-safety certification, or production data.
- No report persistence, historical report store, telemetry, or evaluation dashboard.
- No Azure Speech implementation.
- No autonomous diagnosis, treatment, or clinical decision-making.

These limits are part of the safety and evidence boundary, not missing evaluation scores.
