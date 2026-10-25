# Remediation Validation Feedback Technical Design

## 1. Scope

Implement the bounded contract in
[functional-design-remediation-validation-feedback.md](../functional/functional-design-remediation-validation-feedback.md).

The shared remediation execution layer owns baseline comparison, diagnostic
selection, retry context, and workspace restoration. Provider control planes
only persist the final execution outcome and render it.

## 2. Existing Boundary

`PatchExecutionService` already owns patch application, validation, rollback,
and retry. It currently regenerates a patch after any failed validation without
passing validation evidence to the generator. Extend this service rather than
adding a provider-specific runner or a second retry loop.

The loop runs before commit, branch push, and change-request publication. It
does not alter work-item lifecycle selection, recovery commands, or review
projection.

## 3. Shared Models

Add provider-neutral models under `models/analysis.py`:

```text
ValidationBaseline
  result: ValidationResult

ValidationDiagnostic
  command: str
  file_path: str
  excerpt: str

ValidationComparison
  outcome: passed | baseline_preserved | actionable_regression | unscoped_regression
  baseline: ValidationResult
  post_edit: ValidationResult
  new_relevant_diagnostics: list[ValidationDiagnostic]
  baseline_failure_count: int
  blocking_reason: str | None
```

Extend `PatchExecutionResult` and the remediation execution result with the
comparison object. Keep existing `ValidationResult` fields intact for CLI and
compatibility consumers.

Extend `FailureDetails` only with a compact validation-outcome field if it is
needed for provider-managed work-item rendering. Do not persist raw command
output beyond the existing bounded excerpts.

## 4. Shared Services

Add a small package:

```text
services/remediation/validation_feedback/
  validation_baseline_service.py
  validation_comparison_service.py
  validation_feedback_builder.py
```

`ValidationBaselineService` runs configured validation through the existing
`Validator` after validation setup and before patch application. It returns the
complete ordered `ValidationResult`. An empty command list retains the current
no-validation behavior.

`ValidationComparisonService` requires complete, consistent results for the
configured ordered command sequence. Operational failures are rejected before
baseline acceptance, including repeated failures or a later clean result after
an unusable baseline. Failure counts count commands, not diagnostics.

Pure `diagnostic_parser.py` recognizes MyPy plain text and Ruff concise/default
console output. It retains each diagnostic occurrence and rejects unexpected
output; only recognized summaries, notes, and presentation context are omitted.
Unknown commands require exact stdout/stderr and exit-code equality for a
preserved failure. Tool-specific filtering never applies to other commands.

Frozen, non-persisted `ToolDiagnostic`, `ParsedValidationOutput`, and
`SourceChange` records live in `models/validation_evidence.py`. The snapshot
service alone reads source contents. Pure `source_line_mapping.py` maps equal
source lines from the original snapshot to each attempted result. Relocation
of repeated text is withheld as ambiguous; changed lines and missing contents
have no map. Columns remain part of identity on unchanged mapped lines.
Structured comparison subtracts multisets, never sets or total error counts.
Codes, messages, severities, paths, locations, and duplicate occurrences remain
significant. Only new diagnostics in safe `files_touched` paths reach feedback.

The service returns deterministic, path-and-line-sorted diagnostics. A clean
post-edit result is `passed`; known baseline-only failures are
`baseline_preserved`; new relevant diagnostics are `actionable_regression`; and
other new failures are `unscoped_regression`.

`ValidationFeedbackBuilder` converts only an actionable regression into a
bounded structured-edit prompt addition. It includes edited paths, command,
exit code, and at most ten excerpts totaling 4,000 characters. It explicitly
excludes baseline-only and unscoped output.

## 5. Patch Execution Changes

When `config.remediation.validation_feedback_enabled` is true,
`PatchExecutionService.execute()` must:

1. run setup and retain the existing clean-workspace guard;
2. capture one baseline before the initial patch;
3. apply the patch and run post-edit validation;
4. compare post-edit output with the baseline;
5. continue only for `passed` or `baseline_preserved`;
6. restore and regenerate once only for `actionable_regression`;
7. restore and return structured failure for `unscoped_regression` or an
   exhausted correction attempt.

The baseline and original source snapshot are captured once, after setup and
before the first patch. Every correction compares against that original
baseline and its actual source changes, not the previous failed patch. Missing
source evidence blocks with rollback. Content-free info logs report enabled
mode, comparison outcome, and the blocking reason. Source snapshots are never
persisted or forwarded as validation feedback.

When the feature is disabled, retain the existing execution flow exactly. The
implementation must make this an explicit branch rather than mixing two retry
semantics in one loop.

## 6. Prompt, Publication, And Persistence

Extend the structured-edit prompt context with an optional validation-feedback
section, absent unless an actionable comparison exists. The retry must retain
the original allowed file set.

Publication receives deterministic final validation text:

- clean validation: command summary as today;
- preserved baseline: a concise notice that failures existed before the change
  and were not made worse within the edited scope.

New publication descriptions include `## Validation` independently of feedback
mode. Shared execution passes its actual `ValidationResult` through publication;
when comparison evidence exists, its post-edit result takes precedence. Empty
successful results report `No validation commands configured`, never a clean
validation pass. Missing retained results report `Validation evidence
unavailable`, including publication-only retries without the original evidence.
Only command names and status are rendered, not captured output or summaries.
This presentation does not change publication eligibility, persist new evidence,
or refresh descriptions after same-request revisions.

No provider publisher or control-plane adapter may parse raw validator output.
`WorkItemExecutionFailure` remains the compact persisted record for blocked
attempts; add only an outcome qualifier and existing command/exit details needed
for GitHub and GitLab rendering.

## 7. Implementation Slices

### Phase 9a: Contract And Baseline

- add opt-in configuration and model coverage;
- add baseline capture after setup;
- preserve disabled behavior exactly;
- add deterministic baseline result tests.

### Phase 9b: Comparison And Feedback

- implement safe path extraction and baseline subtraction;
- classify all four outcomes;
- build bounded feedback for edited-file regressions;
- add retry prompt coverage without provider imports.

### Phase 9c: Execution And Persistence

- wire comparison outcomes into patch execution and rollback;
- publish only clean or baseline-preserved attempts;
- persist concise blocked evidence consistently on GitHub and GitLab.

### Phase 9d: Live Rollout

- enable in one GitHub and one GitLab issue-mode repository;
- validate a baseline-only failure, an edited-file regression corrected by one
  retry, and an unscoped regression that blocks cleanly;
- decide whether to change the configuration default after observing costs and
  operator clarity.

## 8. Deferred Work

- structured diagnostic parsers for SARIF, pytest, and other unsupported tools;
- multi-file repair and test-repair loops;
- review-finding-driven revision of an already-published PR/MR;
- more than one feedback-driven correction attempt;
- automatic retry of transient provider or validation-environment failures.
