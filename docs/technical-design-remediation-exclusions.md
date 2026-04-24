# ZeroOne Ops Remediation Exclusions Technical Design

## 1. Scope

This document defines a small technical design for exclusion-first operator
feedback in dashboard-backed remediation.

The goal is to let operators exclude issue classes that repeatedly waste time
without requiring a full allowlist, while keeping the exclusion model general
enough to support multiple remediation work-item sources over time.

This is intentionally a small v1/v1.1 design slice, not a new platform-scale
architecture track.

## 2. Design Goals

- keep remediation broadly eligible inside existing safety boundaries
- let operators exclude problematic issue classes with low effort
- store exclusions as a durable learning surface for later product work
- avoid making the exclusion contract SonarQube-specific
- keep hard safety guards independent from operator-managed exclusions

## 3. Core Direction

Exclusions should be modeled as a source-agnostic control layer.

Even if the first practical rollout mostly excludes SonarQube findings by rule
id, the data model should not assume that all remediation work comes from
SonarQube forever.

Examples of future exclusion keys:

- SonarQube: `source=sonarqube`, `issue_key=python:S1125`
- pipeline failure: `source=pipeline_failure`, `issue_key=mypy:arg-type`
- security scan: `source=security_scan`, `issue_key=semgrep:python.lang.correctness`

## 4. Exclusion Record Model

Suggested record shape:

- `source`
- `issue_key`
- `scope` (optional)
- `reason`
- `updated_at`
- `updated_by` (optional when identity is available)

Field guidance:

- `source`
  - identifies the remediation producer family
  - examples: `sonarqube`, `pipeline_failure`, `security_scan`
- `issue_key`
  - the source-specific normalized exclusion key
  - examples: Sonar rule id, normalized pipeline failure code, scanner rule id
- `scope`
  - optional narrowing such as a path prefix or bounded source-local context
  - should remain optional in the first implementation
- `reason`
  - short operator-facing explanation for why the issue class is excluded
- `updated_at`
  - last modification timestamp for auditability
- `updated_by`
  - optional operator identity when it is available from the execution context

Suggested first implementation constraint:

- require `source` and `issue_key`
- keep `scope` optional and simple
- do not add broad matching logic yet

## 5. Storage Direction

The first implementation should keep exclusions repo-scoped.

Why:

- different repositories can tolerate different remediation risk
- one repo's exclusions should not become global product truth
- the current product already treats state and dashboard behavior as
  repository-local operational context

Reasonable v1 shape:

- persist exclusions in the existing repo-local state/config layer
- keep the storage schema simple and inspectable
- avoid adding a new remote system or external database just for exclusions

## 6. Matching Contract

Eligibility should consult exclusions before normal remediation issue
selection.

High-level rule:

- if a work item matches an explicit exclusion, skip it before normal selection

Suggested first matching contract:

1. match exact `source`
2. match exact `issue_key`
3. if `scope` is present, require the item to satisfy the scope

Examples:

- SonarQube item with rule `python:S1125`
  - skipped by exclusion `source=sonarqube`, `issue_key=python:S1125`
- pipeline failure item with normalized key `pytest:test-failure`
  - skipped only by exclusions for `pipeline_failure`, not by SonarQube entries

Out of scope for v1:

- fuzzy matching
- inheritance between sources
- global exclusion inheritance across repositories
- free-form natural-language matching

## 7. Operator Interaction Shape

The operator path should stay lightweight and structured.

Preferred v1 direction:

- add/remove exclusion through a bounded command or small dashboard action
- avoid free-form text parsing as the primary contract

Desired behavior:

- operators can add an exclusion with a source, issue key, and short reason
- operators can list current exclusions
- operators can remove an exclusion deterministically

The UX should optimize for low effort, not for building a full policy engine.

## 8. Eligibility Integration

Exclusions should be one filter inside the current remediation eligibility
pipeline.

Recommended order:

1. load candidate work item
2. apply hard built-in safety guards
3. apply operator-managed exclusions
4. continue with normal eligibility and selection

Important boundary:

- operator-managed exclusions should never weaken hard safety rules
- they only narrow what the bot will attempt

Examples of safety rules that should stay independent:

- rename-style issue guard
- unsafe multi-file remediation boundaries
- unsupported workflow/source types

## 9. Visibility And Learning Loop

Exclusions should remain easy to inspect later.

The system should make it easy to answer:

- which issue classes are currently excluded
- which source they belong to
- why they were excluded
- whether the same patterns keep recurring

That accumulated data should become a product-learning surface for later:

- prompt improvements
- context improvements
- workflow changes
- post-v1 architecture work

## 10. Testing Guidance

The first implementation should cover:

- persistence and loading of exclusion records
- exact source + issue-key matching
- optional scoped matching when scope is present
- skipped remediation behavior for excluded items
- proof that built-in safety guards still apply independently

## 11. Initial Guardrails

- do not make the model SonarQube-only
- do not introduce free-form matching for v1
- do not require operators to maintain a full inclusion taxonomy
- do not let exclusions silently override hard safety boundaries
- do not treat one repo's exclusions as a universal platform truth
