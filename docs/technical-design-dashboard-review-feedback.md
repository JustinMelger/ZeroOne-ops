# ZeroOne Ops Dashboard Review Feedback Technical Design

## 1. Scope

This document defines the technical design for attaching structured review
feedback to dashboard-backed remediation items after the current hardening
phase.

It builds on:

- [functional-design-dashboard-remediation.md](functional-design-dashboard-remediation.md)
- [technical-design-dashboard-remediation.md](technical-design-dashboard-remediation.md)
- [functional-design-pr-review.md](functional-design-pr-review.md)
- [technical-design-pr-review.md](technical-design-pr-review.md)

Initial constraints:

- GitLab only,
- dashboard remains the remote control plane,
- merge request notes remain the human-facing review output,
- retries stay bounded and opt-in through lifecycle rules,
- no broad new persistence system in the first version.

## 2. Technical Objectives

- Store structured review metadata on remediation dashboard items.
- Avoid making raw MR note prose the only source of retry context.
- Preserve current review workflow behavior while adding dashboard linkage.
- Reuse existing dashboard services where possible.
- Keep future retry logic deterministic and easy to test.

## 3. Recommended Technical Direction

The remediation item should be the primary dashboard record.

That means the next version should prefer:

- enriching remediation items with review metadata,
- de-emphasizing standalone review-status items for remediation retry logic,
- keeping standalone review mirror items only if they still add operator value
  for non-remediation reviews.

This avoids forcing reconciliation or retry logic to join two dashboard items
when one item can hold the needed state.

## 4. Repository Layout

Suggested additions or follow-up changes:

```text
zeroone-ops/
  docs/
    functional-design-dashboard-review-feedback.md
    technical-design-dashboard-review-feedback.md
  src/ai_sonar_bot/
    models/
      dashboard.py
    services/
      review_dashboard_updater.py
      dashboard_reconciliation_runner.py
      dashboard_remediation_runner.py
      remediation_context_builder.py
```

The exact file set can vary, but the new behavior should stay centered on the
existing dashboard lifecycle services rather than creating a second unrelated
retry state system.

## 5. Dashboard Data Model Direction

### 5.1 Extend `DashboardItem`

Recommended new or expanded fields:

- `review_note_url: str | None`
- `review_findings_count: int | None`
- `review_feedback_summary: str | None`
- `review_feedback_updated_at: datetime | None`
- `review_confidence: float | None`
- `review_confidence_reason: str | None`
- `retry_count: int | None`
- `retry_eligible: bool | None`
- `retry_block_reason: str | None`

Existing fields already useful for this design:

- `merge_request_iid`
- `merge_request_url`
- `commit_sha`
- `reviewed_head_sha`
- `review_status`
- `log_excerpt`

### 5.2 Normalization Rule

For remediation-backed review state:

- `reviewed_head_sha` must match the reviewed MR revision,
- review metadata should be updated on the remediation item tied to that MR,
- later retries should only trust review state that matches the prior attempt's
  MR traceability.

## 6. Workflow Ownership Boundaries

Before implementation, the platform should treat workflow ownership as
explicit rather than implied.

### 6.1 Remediation Owns

Remediation should own:

- active code-change attempts,
- consuming retry context when a new attempt starts,
- incrementing retry counters when a real retry is launched,
- writing remediation lifecycle fields it directly observes during execution.

Remediation should not own:

- generating review judgments,
- interpreting raw MR discussion as retry state,
- final post-MR lifecycle convergence after the active run ends.

### 6.2 Review Owns

Review should own:

- structured review result generation,
- MR note publishing,
- writing review metadata to the linked dashboard item when traceability is
  available,
- deciding whether the review outcome is `no_findings`, `findings_present`, or
  `manual_review_only`.

Review should not own:

- reopening remediation items,
- incrementing remediation retry counts,
- deciding whether a retry is actually executed.

### 6.3 Reconciliation Owns

Reconciliation should own:

- post-merge-request lifecycle convergence,
- deciding whether an item becomes `done`, reopens, or moves to `failed`,
- preserving linked review metadata during lifecycle transitions,
- attaching bounded retry eligibility signals derived from lifecycle plus prior
  review state.

Reconciliation should not own:

- generating new review findings,
- rewriting prior review judgments,
- executing remediation retries itself.

### 6.4 Dashboard State Owns

The dashboard item should be the canonical machine-readable record for:

- remediation lifecycle status,
- MR traceability,
- review linkage,
- retry eligibility and retry history fields.

Local state may still cache run-level details, but cross-workflow automation
should prefer the dashboard item as the shared control-plane record.

### 6.5 Operator Surface Versus Machine Surface

The platform should keep these surfaces distinct:

- merge request notes are for operators,
- dashboard fields are for automation and operator traceability,
- local state is for run bookkeeping and dedupe.

This separation should remain visible in implementation choices so one workflow
does not silently take ownership of another workflow's surface.

## 7. Review Dashboard Update Path

`ReviewDashboardUpdater` should evolve from creating only standalone
`review_status` items toward one of these modes:

1. preferred for remediation MRs:
   update the linked remediation item with structured review metadata,
2. acceptable fallback for normal human-authored MRs:
   continue mirroring a standalone review-status item when there is no linked
   remediation dashboard item.

This keeps the remediation retry path dashboard-centered without removing the
useful review mirror for unrelated merge requests.

## 8. Linking Strategy

The update path needs a deterministic link from a reviewed MR back to the
remediation item.

Recommended link sources, in priority order:

1. dashboard item traceability already storing `merge_request_iid`,
2. exact `merge_request_url`,
3. branch name and commit SHA when earlier traceability is incomplete,
4. remediation-authored MR metadata parsed from the description only as a
   bounded fallback.

The updater should not rely only on free-form note text or fuzzy title
matching.

## 9. Reconciliation Changes

`DashboardReconciliationRunner` should later:

- load remediation items already carrying review metadata,
- preserve that review metadata when reopening or failing an item,
- optionally append a short operator summary when a reopened item has prior
  findings,
- set retry-related fields when the lifecycle result makes retry possible.

This keeps review state attached to the same item across MR lifecycle changes.

## 10. Retry Consumption Path

When a remediation item is selected for a later retry, the remediation context
builder should be able to include bounded prior review state such as:

- previous `review_status`,
- `review_feedback_summary`,
- selected structured findings,
- prior `review_confidence`,
- retry count and retry block reason.

The prompt should receive that as explicit machine context, not as raw pasted
MR note prose.

## 11. Retry Safety Rules

The first retry-aware implementation should enforce:

- bounded retry count,
- no retry when the latest review outcome is too ambiguous,
- no retry when traceability between dashboard item and reviewed SHA is broken,
- no retry based solely on low-signal human discussion threads,
- visible operator-facing explanation when retry is blocked.

## 12. Rendering Direction

The dashboard renderer should later surface a compact view of review state on
remediation items, for example:

- review status,
- findings count,
- reviewed SHA,
- retry eligibility,
- short retry block or failure note.

That should appear in the remediation item's summary/table view rather than
forcing operators into the raw JSON details block.

## 13. Migration Strategy

Recommended incremental migration:

1. add new review metadata fields to `DashboardItem`,
2. teach the updater to enrich remediation items when a link is available,
3. keep standalone review-status items temporarily for non-remediation cases,
4. update rendering and reconciliation to show and preserve the new fields,
5. add retry-aware remediation context only after the metadata path is stable.

## 14. Testing Strategy

Add coverage for:

- linking a reviewed remediation MR back to the correct dashboard item,
- preserving review metadata when reconciliation reopens or fails an item,
- retry selection that respects retry bounds and traceability,
- rendering review state clearly in the dashboard summary table,
- fallback behavior for human-authored MRs with no remediation dashboard item.

## 15. Open Decisions

The next implementation phase should resolve:

- whether standalone `review_status` items remain for all MRs or only
  non-remediation reviews,
- how many structured findings should be stored on the dashboard item,
- which review outcomes make an item retry-eligible,
- whether retry state should live only on the dashboard item or also in local
  state,
- how much of prior review context should be passed back into remediation
  prompts without overfitting to one previous review.

## 16. Done When

This design is realized when:

- remediation dashboard items hold structured review metadata,
- review updates can link reliably back to remediation items,
- reconciliation preserves that review state,
- later remediation attempts can consume bounded prior review feedback through
  structured dashboard context.
