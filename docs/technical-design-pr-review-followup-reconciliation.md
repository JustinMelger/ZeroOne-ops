# PR Review Follow-Up Reconciliation Technical Design

## 1. Scope

This document defines a small technical design for reconciling the current
review pass against the most recent prior review pass on the same merge
request.

It extends the existing review-memory design and focuses on better follow-up
wording, not on a large new review schema.

## 2. Technical Objectives

- Compare current findings to the latest prior review findings for the same MR.
- Derive conservative follow-up outcome signals:
  - repeated unresolved,
  - appears resolved,
  - new finding.
- Feed those signals into note rendering so repeated reviews read like
  follow-up passes.
- Keep the implementation deterministic and bounded.

Agreed first-version decisions:

- compare only against the latest prior review pass
- use note wording first before changing the structured review result shape
- do not add explicit stored finding fingerprints yet
- mention resolved earlier findings in both no-findings and mixed new-finding
  cases when continuity benefits
- keep mixed resolved-plus-new summaries to one short line
- when matching or resolution is ambiguous, fall back to neutral follow-up
  wording or explicit unable-to-verify language

## 3. Proposed Architecture Direction

Add a small reconciliation step after review analysis and before note
rendering:

1. run the current review normally,
2. load the latest prior review pass from bounded review state,
3. compare prior findings to current findings,
4. derive a compact follow-up reconciliation result,
5. render the note using that result.

This should remain review-owned logic and should not move into dashboard or
reconciliation workflows.

## 4. Proposed Internal Model

The first version can use a compact internal helper model such as:

```python
class FollowUpFindingStatus(BaseModel):
    summary: str
    file_path: str | None = None
    status: Literal["still_unresolved", "appears_resolved", "new"]


class FollowUpReviewReconciliation(BaseModel):
    prior_reviewed_head_sha: str
    still_unresolved: list[FollowUpFindingStatus] = Field(default_factory=list)
    appears_resolved: list[FollowUpFindingStatus] = Field(default_factory=list)
    new_findings: list[FollowUpFindingStatus] = Field(default_factory=list)
```

The exact shape can change, but it should stay internal and bounded in the
first version.

## 5. Matching Strategy

Use a conservative finding match heuristic against the latest prior review
pass.

The first version should compare using a bounded normalized key built from:

- file path when present,
- finding title,
- and normalized summary or evidence-adjacent finding text.

Rules:

- if a current finding matches a prior finding key, treat it as
  `still_unresolved`
- if a prior finding key has no matching current finding, treat it as
  `appears_resolved`
- if a current finding has no prior match, treat it as `new`

This does not need to solve fuzzy identity perfectly. It needs to improve
operator trust while staying predictable.

If matching confidence is weak, prefer under-matching over claiming that a
prior finding has clearly resolved.

## 6. Service Responsibilities

### 6.1 Review State Service

No large storage redesign is needed.

It already stores bounded prior review passes and normalized finding summaries.
That existing state should remain the primary input to follow-up
reconciliation.

### 6.2 Review Runner Or Review Analysis Adapter

Add a small step that:

- loads the latest prior review pass,
- invokes follow-up reconciliation,
- attaches the derived result to the current review rendering path.

This should happen after the current review result is known, not during prompt
construction.

### 6.3 Review Publisher

Use follow-up reconciliation to render clearer note language.

Target behaviors:

- unresolved repeated finding:
  - `Follow-up review: the earlier concern about X still appears unresolved.`
- resolved prior finding with no new issues:
  - `Follow-up review: the earlier concern about X no longer appears present.`
  - `No new actionable findings in this review pass.`
- new finding after a prior finding:
  - `Follow-up review: the earlier concern about X no longer appears present, but a new issue now appears around Y.`
- ambiguous resolution:
  - `Follow-up review: the earlier concern about X is not restated here, but the current pass could not verify conclusively whether it is fully resolved.`

The first version should keep this concise and avoid long history blocks.

## 7. Boundaries

- Review owns follow-up reconciliation and wording.
- Review memory remains the source of prior-pass context.
- Dashboard does not own this matching logic.
- Remediation and reconciliation workflows do not consume this review-thread
  wording logic directly.

## 8. Risks

### 8.1 False Resolution Claims

Risk:

- the bot may claim a prior finding is resolved when the visible code is still
  ambiguous.

Mitigation:

- keep matching conservative,
- require visible absence of the prior concern in the current findings before
  using explicit resolved wording,
- allow neutral or unable-to-verify wording in borderline cases.

### 8.2 Noisy History Recaps

Risk:

- repeated notes become verbose if too much prior state is rendered.

Mitigation:

- compare mainly against the latest prior pass first,
- summarize only the most relevant unresolved or resolved outcomes,
- keep the note focused on the current review pass.

### 8.3 Weak Finding Matching

Risk:

- simple summary matching may connect the wrong findings.

Mitigation:

- combine file path, title, and normalized summary,
- prefer under-matching over overconfident matching,
- avoid strong resolved wording when the match is weak.

## 9. Recommended Implementation Order

1. define a compact internal follow-up reconciliation helper/model,
2. compare current findings with the latest prior review pass,
3. update note rendering for:
   - still unresolved,
   - appears resolved,
   - new finding,
4. add regression tests for the three main sequences:
   - first finding reported,
   - same finding still present,
   - earlier finding resolved,
   - ambiguous resolution fallback.

## 10. Verification Strategy

Add tests for:

- same MR, same finding on later SHA -> unresolved follow-up wording
- same MR, earlier finding disappears and no new findings -> resolved wording
- same MR, earlier finding disappears but a different new finding appears
- ambiguous match or ambiguous resolution -> avoid overclaiming resolution and
  prefer neutral or unable-to-verify wording

The most important verification outcome is improved operator-facing continuity
without introducing brittle or overconfident matching behavior.
