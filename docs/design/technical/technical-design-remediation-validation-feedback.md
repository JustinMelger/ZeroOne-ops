# Remediation Validation Feedback Technical Design

## 1. Scope

Implement the bounded contract in
[functional-design-remediation-validation-feedback.md](../functional/functional-design-remediation-validation-feedback.md).

The shared remediation execution layer owns baseline comparison, diagnostic
selection, retry context, and workspace restoration. Provider control planes
only persist the final execution outcome and render it.

## 2. Existing Boundary

`PatchExecutionService` owns patch application, validation, rollback,
and retry. Feedback-disabled execution retains its blind regeneration behavior;
feedback-enabled execution uses the shared assessments. Extend this service rather than
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
Unknown commands require clean validation, both at baseline and publication.
Tool-specific filtering never applies to other commands. Pure execution-health
classification is independent of parser recognition, including wrapped tool
errors and narrowly recognized pytest collection-error exit 2.
Parsed output distinguishes unsupported formats from contradictory evidence
and unresolved paths. After a clean baseline, a normal validation failure in an
unsupported format uses command-level correction evidence; strict parsing is
still required to preserve a failed baseline. Malformed consistency evidence
and unresolved paths do not receive that fallback.

Frozen, non-persisted `ToolDiagnostic`, `ParsedValidationOutput`, and
`SourceChange` records live in `models/validation_evidence.py`. The snapshot
service alone reads source contents. Pure `source_line_mapping.py` maps equal
source lines from the original snapshot to each attempted result. Relocation
of repeated text is withheld as ambiguous; changed lines and missing contents
have no map. Columns remain part of identity on unchanged mapped lines.
Structured comparison subtracts multisets, never sets or total error counts.
Codes, messages, severities, paths, locations, and duplicate occurrences remain
significant. Absolute repository-contained locations are normalized before
comparison. Escaping/external paths and unresolved directory-changing invocation
semantics cannot establish structured baseline evidence.

The service returns deterministic, path-and-line-sorted diagnostics. A clean
post-edit result is `passed`; known baseline-only failures are
`baseline_preserved`; new relevant diagnostics are `actionable_regression`; and
other new failures are `unscoped_regression`.

`failure_evidence.py` selects presentation evidence independently of scope
decisions. It sanitizes both streams before selecting exception/diagnostic
summaries and nearby locations, falling back to a bounded tail. Source/local
variable displays are excluded. Excerpts contain at most twenty lines and
2,000 characters, including omission notices.
Pytest's `E File ...` location lines are recognized before filtering `E`-prefixed
source displays, preserving syntax-error origins without introducing attribution
or edit-scope decisions. Credentials, auth headers,
sensitive arguments, credential-bearing URLs, and terminal controls are
redacted when recognizable; this is not universal secret detection.

`FailureDetails` and `WorkItemExecutionFailure` gain optional `validation_phase`,
`baseline_exit_code`, and `diagnostic_excerpt` fields, defaulting to `None`.
New failures retain this canonical sanitized excerpt instead of raw stdout/
stderr prefixes; historical prefix fields remain readable. The assessment's
blocking index selects the corresponding command and baseline exit. Shared
CLI/issue presentation uses the same excerpt and preserves workflow-log links.
Issue HTML is escaped, and final payload-budget checks remain authoritative.

Non-persisted `ValidationCommandAssessment`, `ValidationCorrectionDecision`, and
`ValidationAssessment` separate command health, correction, and publication.
The assessment retains the actual blocking command position, not the first
nonzero exit. Every blocker must be correction-eligible.

`ValidationFeedbackBuilder` accepts that independent decision and produces
command-level evidence: command, baseline/post-edit exits, and bounded failure
context. Allowed edit paths remain separate. The packet contains at most ten
entries and 4,000 characters, discloses omitted failures, and excludes preserved
baseline diagnostics. Empty/unusable evidence withholds correction.

## 5. Patch Execution Changes

When `config.remediation.validation_feedback_enabled` is true,
`PatchExecutionService.execute()` must:

1. run setup and retain the existing clean-workspace guard;
2. capture one baseline before the initial patch;
3. apply the patch and run post-edit validation;
4. compare post-edit output with the baseline;
5. continue only for `passed` or `baseline_preserved`;
6. restore and regenerate at most once when the independent correction decision
   is eligible and usable feedback fits; the publication outcome need not be
   `actionable_regression`;
7. restore and return structured failure when correction is withheld, disabled,
   or exhausted. A later pass/preserved result alone permits publication.

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
attempts, carrying the outcome, phase, command/exit details, and bounded sanitized
excerpt needed for equivalent GitHub and GitLab rendering.

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
- more than one feedback-driven correction attempt;
- automatic retry of transient provider or validation-environment failures.
