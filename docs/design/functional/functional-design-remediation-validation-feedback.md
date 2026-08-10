# Remediation Validation Feedback Functional Design

## 1. Purpose

Define a bounded validation-feedback loop for an automated remediation attempt.

The loop must distinguish failures that already existed in the repository from
regressions introduced by the generated patch. It may request one corrected
patch only when the new diagnostic is sufficiently tied to the file that the
attempt is allowed to edit.

## 2. Goals

- avoid blocking a safe remediation only because the baseline repository already
  has unrelated validation failures;
- give the model concise, concrete feedback when its one-file patch introduced a
  new validation regression;
- retain the current one-file remediation boundary and one bounded retry;
- make the outcome visible to operators and reviewers without treating a
  baseline failure as a successful full validation run;
- preserve the same behavior for GitLab and GitHub.

## 3. Non-Goals

- repairing pre-existing repository failures;
- automatically editing tests or files outside the original patch boundary;
- retrying failed validation indefinitely;
- parsing every validation-tool output format in v1;
- using review findings to revise an already-published change request.

## 4. Validation Feedback Model

For a remediation attempt with validation commands configured, the execution
flow is:

1. run validation environment setup once;
2. capture a baseline result for every configured validation command before
   applying a patch;
3. generate and apply the scoped patch;
4. run the same validation commands after the patch;
5. compare post-edit diagnostics with the baseline;
6. either continue, retry once with bounded feedback, or block the item.

Baseline capture is evidence, not a repair request. The bot must never send
baseline-only failures to the model or claim that it fixed them.

## 5. Outcomes

| Outcome | Meaning | Execution behavior |
|---|---|---|
| `passed` | All post-edit validation commands pass. | Continue to approval and publication. |
| `baseline_preserved` | The repository had known failures, but the patch introduced no new diagnostics relevant to its editable file. | Continue with an explicit baseline warning in execution evidence. |
| `actionable_regression` | The patch introduced a new diagnostic tied to an edited file. | Restore the workspace and request one corrected patch. |
| `unscoped_regression` | A new failure exists but cannot be safely tied to the editable file. | Restore the workspace and block for operator review. |
| `setup_failed` | Validation setup could not prepare a clean environment. | Block without generating a retry. |

`baseline_preserved` is not reported as a clean validation pass. It means the
patch did not make the configured validation evidence worse within the bounded
repair scope. The generated change request must retain that distinction.

## 6. Diagnostic Relevance

V1 uses a conservative text-based relevance rule:

- a diagnostic is eligible for model feedback only when its output identifies a
  normalized repository path that is in the patch's `files_touched` set;
- the diagnostic must be absent from the baseline result for the same command;
- feedback contains only the command, exit code, relevant diagnostic excerpts,
  and the allowed file paths;
- output that is malformed, pathless, outside the repository, or refers to a
  different file is never offered as a request to edit more files.

A command that passes at baseline and fails after the patch is a new failure,
but it remains `unscoped_regression` unless its output can be connected to an
edited file. This favors a clear operator handoff over speculative multi-file
repair.

The first version limits feedback to ten diagnostics and 4,000 total characters
after truncation. Structured tool-specific parsing may improve relevance later,
but it is not required for this phase.

## 7. Retry Rules

- At most one feedback-driven regeneration occurs per remediation attempt.
- The original target, repository scope, constraints, and one-file boundary are
  preserved for the retry.
- The first failed patch is restored completely before corrected patch
  generation.
- The retry receives the original remediation context plus a bounded validation
  feedback packet; it does not receive unrelated baseline output.
- A failed retry, patch-apply failure, or unscoped regression blocks the item
  with the latest execution evidence.

The existing `remediation.max_retry_count` remains the rollout control. During
this phase, validation feedback consumes at most one of its allowed retries;
values greater than one do not create extra validation-feedback attempts.

## 8. Operator Experience

Blocked work-item views should continue to show the concise latest execution
summary, failed command, exit code, retry count, and workflow-run link. Add a
validation outcome qualifier when available:

- `Validation passed.`
- `Validation preserved the existing baseline failures.`
- `Validation introduced a new diagnostic in <file>; one correction attempt was used.`
- `Validation failed outside the one-file repair boundary.`

The pull/merge request description should state either `Validation passed` or
`Validation baseline preserved` with the affected command names. It must not
paste raw validation output into the description.

## 9. Configuration And Rollout

Introduce `remediation.validation_feedback_enabled`, defaulting to `false` for
the first rollout. When disabled, existing validation and retry behavior remain
unchanged. When enabled, baseline comparison replaces blind validation retry
behavior for that repository.

Enable it first in one GitHub and one GitLab issue-mode repository with a known
non-clean validation baseline. Promote it to the default only after live
validation confirms that baseline failures, relevant regressions, and blocked
operator handoffs are rendered clearly.

## 10. Acceptance Criteria

- A pre-existing failure in another file is not sent to the model and does not
  block a non-regressing one-file patch.
- A new diagnostic in an edited file produces at most one corrected-patch
  attempt.
- A new diagnostic outside the editable-file boundary blocks rather than
  expanding the patch scope.
- Workspace restoration occurs before every retry and every terminal failure.
- GitHub and GitLab persist the same execution outcome and render equivalent
  operator evidence.
- Disabled configuration preserves the current remediation behavior.
