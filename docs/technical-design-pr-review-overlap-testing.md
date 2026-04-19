# Technical Design: PR Review Overlap Testing

## 1. Purpose

The current continuity benchmark suite is useful, but it does not fully prove the
runtime overlap path.

Today, the benchmark tests mainly exercise:
- app-owned overlap packet generation
- app-owned overlap normalization

They do **not** fully exercise:
- the runtime overlap analysis service boundary
- fixture-backed LLM overlap responses
- overlap-result validation inside the real review workflow path

This design defines a clearer testing strategy so green continuity tests mean what
we think they mean.

## 2. Problem

The current test set mixes two different goals:
- validating deterministic overlap logic
- validating runtime repeated-review behavior

Those are both valuable, but they belong to different test layers.

Without that separation, we risk over-trusting deterministic benchmark coverage as
proof that the full runtime overlap flow is stable.

## 3. Goals

- Keep deterministic overlap logic easy to test and debug.
- Add runtime overlap tests that exercise the real overlap service boundary.
- Make it obvious which layer each test is proving.
- Keep repeated-review benchmarks as a real regression gate.

## 4. Non-Goals

- Replace the existing deterministic benchmark suite.
- Add live OpenAI calls to automated tests.
- Turn integration tests into large end-to-end scenario fixtures for every case.

## 5. Testing Layers

### 5.1 Deterministic overlap benchmarks

Purpose:
- Validate app-owned overlap packet generation.
- Validate app-owned normalization rules.
- Keep candidate narrowing and ambiguity handling explainable.

This layer should:
- avoid the LLM entirely
- call packet builder and deterministic reconciliation directly
- remain the main place for tightly controlled continuity scenarios

Examples:
- repeated same concern across passes
- structured/unstructured wording drift
- sibling issue separation
- cross-file non-overlap
- one-to-many ambiguity

These tests prove:
- the app-owned substrate behaves correctly

These tests do **not** prove:
- the runtime overlap service boundary
- LLM overlap output validation
- review-runner wiring

### 5.2 Overlap runtime fixture tests

Purpose:
- Validate the real overlap runtime path using fixture-backed overlap output.
- Prove that runtime overlap behavior is bounded and safe.

This layer should:
- go through `ReviewOverlapAnalysisService`
- use fixture-backed or fake overlap responses
- validate rejection of invalid or contradictory overlap output
- validate accepted overlap output that stays inside the packet boundary

Examples:
- wrong prior SHA rejected
- indices out of range rejected
- candidate-boundary escape rejected
- duplicate current/prior reuse rejected
- valid bounded overlap accepted

These tests prove:
- the overlap service boundary is working
- the app still owns the allowed result space

### 5.3 Review workflow integration tests

Purpose:
- Validate that one review run still behaves correctly with overlap enabled.

This layer should:
- go through `ReviewRunner`
- confirm overlap participates in one operator-facing review run
- confirm note publishing receives overlap output when available
- confirm note publishing degrades gracefully when overlap is missing or invalid

These tests should stay selective and small.

They do not need to cover every continuity benchmark shape.

### 5.4 Live validation examples

Purpose:
- Validate that repeated-review continuity feels right on real merge requests.

This layer is not the same as unit or integration testing.

It should:
- capture real MR sequences
- compare expected human continuity with actual bot continuity
- feed benchmark additions when a real miss repeats

## 6. Proposed Test Ownership

### Deterministic benchmark suite

File direction:
- `tests/ai_sonar_bot/services/test_review_continuity_sequences.py`

Owns:
- packet-builder benchmark cases
- deterministic normalization cases

### Overlap runtime validation suite

File direction:
- `tests/ai_sonar_bot/services/test_review_overlap_analysis_service.py`
- optionally a dedicated runtime fixture file later if this grows

Owns:
- overlap-result boundary validation
- contradictory overlap output rejection
- valid overlap acceptance

### Review-runner integration suite

File direction:
- `tests/ai_sonar_bot/integration/test_runner.py`

Owns:
- one-command review flow
- overlap wiring to publisher
- graceful degradation when overlap is unavailable

## 7. Benchmark Gate

The continuity benchmark suite should remain a regression gate, but with a clear
label:
- it is the gate for deterministic overlap behavior
- it is not by itself the gate for full runtime overlap correctness

For runtime overlap confidence, we also need:
- overlap-analysis validation tests
- selected review-runner integration coverage

## 8. Success Criteria

This design is successful when:
- deterministic benchmarks clearly test app-owned overlap behavior
- runtime overlap tests clearly test the analysis-service boundary
- integration tests prove the review run remains cohesive
- failures can be localized quickly to the correct layer
- green tests no longer imply more than they actually cover

## 9. Implementation Notes

Short-term follow-up:
1. keep the current deterministic benchmark suite in place
2. continue expanding runtime overlap validation tests when new boundary bugs appear
3. add at least one integration test that proves overlap omission degrades note wording cleanly
4. keep using live MR examples to drive new deterministic benchmark cases

## 10. Recommendation

Adopt this layered testing model without replacing the current benchmark suite.

That keeps the current continuity work valuable, while making the real runtime
coverage clearer and more trustworthy.
