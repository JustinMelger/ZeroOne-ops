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
| `unscoped_regression` | Validation does not meet publication requirements, including command-level failures. | Restore; independently assess eligibility for one constrained correction, otherwise block. |
| `setup_failed` | Validation setup could not prepare a clean environment. | Block without generating a retry. |

`baseline_preserved` is not reported as a clean validation pass. It means the
patch did not make the configured validation evidence worse within the bounded
repair scope. The generated change request must retain that distinction.

## 6. Diagnostic Relevance

V1 uses bounded MyPy plain-text and Ruff concise/default-console parsing:

- normalize supported diagnostic paths against the trusted repository root;
  absolute and relative aliases must share identity, and unresolved paths block;
- compare diagnostic multisets for the same ordered command, retaining path,
  severity, code, message, line, column, and duplicate occurrences; removed
  diagnostics are improvements, while increased occurrences are regressions;
- recognize only tool summaries and presentation context. Unexpected output
  blocks rather than silently disappearing from the comparison;
- actual pre-edit and post-edit source contents may prove that an unchanged
  line moved after an insertion/deletion. Changed lines, ambiguous repeated
  source text, and missing mapping evidence never establish relocation;
- feedback contains only the command, exit code, relevant diagnostic excerpts,
  and the allowed file paths;
- output that is malformed, pathless, outside the repository, or refers to a
  different file is never offered as a request to edit more files.

A previously passing command that now reports a normal validation failure may
receive one correction, regardless of language or diagnostic paths. Importing
tests and traceback callers are evidence, not additional editable files. This
observation justifies an attempt, not proof that the patch caused the failure.
Execution health, correction eligibility, and publication are separate decisions.

Feedback remains limited to ten diagnostics and 4,000 total characters.
Unsupported commands, including pytest, must pass at baseline and before
publication. Identical failed output never authorizes remediation. A generic
exit 1 with nonempty evidence permits correction unless operational evidence
is detected. Pytest exit 2 permits correction only with collection-error and
exception evidence; usage errors, interruption, and no tests collected block.
Other unknown nonzero exits remain unclassified. Timeouts, unavailable/non-executable tools, terminated processes,
scanner execution errors, and incomplete/contradictory evidence always block,
even when identical at baseline. These failures never trigger model correction.
The default remains opt-in; this prevents regressions, not proof that all
targeted scanner findings have been resolved.

## 7. Retry Rules

- At most one feedback-driven regeneration occurs per remediation attempt.
- The original target, repository scope, constraints, and one-file boundary are
  preserved for the retry.
- The first failed patch is restored completely before corrected patch
  generation.
- The retry receives the original remediation context plus a bounded validation
  feedback packet; it does not receive unrelated baseline output.
- Every blocking command must permit correction. Mixed operational failures
  prevent regeneration even when another failure would otherwise qualify.
- A failed retry, patch-apply failure, or ineligible correction blocks with
  latest execution evidence. Publication still requires passed or reliably
  preserved diagnostics; an LLM response never establishes validation success.

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
