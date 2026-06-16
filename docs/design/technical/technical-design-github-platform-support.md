# ZeroOne Ops GitHub Platform Support Technical Design

## 1. Scope

This document defines a technical design direction for making GitHub a
first-class ZeroOne Ops platform.

This is intentionally broader than review-only support. The long-term target is
not:

- GitHub review as a one-off transport adapter,

but:

- GitHub review support,
- GitHub remediation support,
- a GitHub-native work-queue or dashboard-equivalent control plane,
- a coherent operator story for GitHub-hosted repositories.

At the same time, this document does not promise immediate feature parity in
one step. The goal is to design the platform expansion carefully enough that we
do not rush into shallow parity or brittle abstractions.

## 2. Why This Matters

GitHub platform support matters for three reasons:

- product visibility
  - full GitHub support is a clearer product story than partial provider
    support
- direct dogfooding
  - ZeroOne Ops can review and eventually remediate its own repository with the
    same product surface we want to offer externally
- architecture timing
  - provider seams are still visible enough that extracting them now is likely
    cheaper than waiting until more GitLab assumptions harden further

## 3. Current State In Code

ZeroOne Ops is currently GitLab-first in two different ways:

### 3.1 Review

The review core is partly reusable:

- candidate generation
- precision / reconciliation
- artifact building
- artifact validation
- continuity logic

But transport and orchestration remain GitLab-shaped:

- `providers/gitlab_review_client.py`
- `services/review/mr_intake.py`
- `services/review/review_gitlab_prior_context_service.py`
- `services/review/review_gitlab_prior_note_parser.py`
- `services/review/review_publisher.py`
- `services/review/review_runner.py`

### 3.2 Dashboard And Remediation

The dashboard and dashboard-backed remediation are more deeply GitLab-native:

- one persistent GitLab issue as the work queue / control plane
- note-driven operator policy commands
- GitLab issue update lifecycle for dashboard items
- merge-request lifecycle transitions tied to GitLab semantics

So the platform expansion problem is not only a review problem. Review is the
most portable slice today, but full GitHub support eventually requires a
GitHub-native control-plane and remediation story too.

## 4. Design Goals

- Design GitHub support as a serious platform expansion, not an opportunistic
  transport patch.
- Preserve the current review and remediation safety boundaries while
  introducing provider-neutral seams.
- Reuse the existing review core where it is genuinely provider-neutral.
- Avoid forcing GitHub to mimic GitLab where the product surface should differ.
- Support phased delivery without pretending that early phases equal full
  parity.

## 5. Non-Goals

- one-step GitHub/GitLab parity across every workflow,
- replacing GitLab as the primary mature platform immediately,
- inventing one giant abstraction that covers every provider and every workflow
  before we understand the real seams,
- rushing dashboard/remediation parity before the GitHub control-plane model is
  clear.

## 6. Boundary Principles

### 6.1 Review Authority Stays In Review

Provider support must not move review authority out of the current review
stages.

The review core still owns:

- what findings are true,
- what advisory output survives,
- continuity meaning,
- output safety before publish.

Provider layers only own:

- intake,
- diff/data fetch,
- publication transport,
- provider-backed continuity retrieval.

### 6.2 Remediation Stays Focused On Fixes

GitHub remediation support must preserve the current remediation boundary:

- remediation executes selected fixes,
- remediation does not become a second review surface,
- any GitHub-native control plane should still separate issue selection from
  fix execution.

### 6.3 Provider-Neutral Core, Provider-Specific Surfaces

We should make core contracts provider-neutral where it helps:

- review candidate/context models,
- continuity identity fields,
- remediation execution targets,
- run-state concepts that should survive across providers.

But we should keep genuinely provider-specific surfaces explicit:

- GitLab issue dashboard vs future GitHub control-plane surface,
- GitLab MR notes vs GitHub PR comments,
- inline-comment/thread semantics,
- CI event context and auth loading.

## 7. Platform Shape

GitHub platform support should be treated as four related but separate product
slices:

1. GitHub review
2. GitHub remediation
3. GitHub work queue / dashboard-equivalent control plane
4. GitHub operator control / policy interaction model

These should share architecture where appropriate, but they should not be
forced into one huge first implementation.

## 8. Review Architecture Direction

### 8.1 Introduce A Provider-Neutral Review Platform Interface

Add a review-facing provider protocol, for example:

- `ReviewPlatformClient`

Responsibilities:

- fetch one PR/MR candidate from CI context,
- fetch full reviewable pull request details with changed files and diff data,
- fetch current PR/MR state for same-SHA and reconciliation checks,
- publish summary review output,
- update summary review output,
- publish inline comments when enabled,
- list prior machine-managed review notes/comments,
- resolve current bot author identity.

Implementations:

- `GitLabReviewPlatformClient`
- `GitHubReviewPlatformClient`

### 8.2 Move Toward Provider-Neutral Review Naming

Current names like:

- `MergeRequestReviewCandidate`
- `MergeRequestReviewContext`
- `MergeRequestChangedFile`

should evolve toward provider-neutral review naming, for example:

- `PullRequestReviewCandidate`
- `PullRequestReviewContext`
- `PullRequestChangedFile`

This does not require one giant rename first, but the design direction should
be explicit.

### 8.3 Keep The Staged Review Pipeline

GitHub support should reuse the existing staged review core rather than
redesign it:

- `ReviewCandidateGenerationService`
- `ReviewReconciliationService`
- `ReviewArtifactBuilder`
- `ReviewArtifactValidator`
- continuity and overlap services

The provider expansion should prove that these services are truly the reusable
core.

### 8.4 Review Publication Model

GitHub review should preserve the current authority model:

- one authoritative summary review surface per reviewed head SHA
- machine-safe payload embedded in that summary surface
- inline comments subordinate to the summary record

Likely first transport:

- GitHub pull request summary comment

Likely later transport:

- GitHub review comments / threads

Inline support should be phased after summary-comment continuity is stable.

## 9. Remediation Architecture Direction

GitHub remediation support is not just “open a PR instead of an MR.”

It requires decisions about:

- how selected work items are represented outside the GitLab issue dashboard
- how lifecycle state is stored remotely
- how remediation status and retryability are exposed to operators
- how review outcomes feed back into future remediation attempts

Provider-neutral remediation execution can still be reused:

- context building
- analysis
- structured-edit generation
- patch application
- validation
- publish-side branch/PR creation

But the intake and work-queue control plane cannot simply assume the current
GitLab dashboard issue model.

## 10. Control Plane Direction

The current dashboard is very GitLab-native:

- one persistent issue
- machine-managed markdown
- note-driven policy commands
- issue-based remediation queue and status

For GitHub, we should not assume the exact same surface blindly.

Possible directions later could include:

- one persistent GitHub issue as a rough dashboard equivalent
- a lighter PR/issue-label driven control plane
- a separate external control plane if GitHub-native ergonomics prove too weak

This should be designed deliberately rather than inherited accidentally from
the GitLab issue model.

## 11. Configuration Direction

Review and remediation policy should stay mostly provider-neutral:

- `review`
- `remediation`

Provider-specific connection/auth settings should stay separate, for example:

- GitLab connection variables
- GitHub connection variables

Provider choice should primarily come from CI/runtime context rather than
stuffing provider switching into review/remediation policy config.

## 12. CI And Entry Point Direction

We should preserve the current high-level commands where possible:

- `zeroone-ops review`
- `zeroone-ops dashboard ...` or later provider-neutral control-plane commands

Platform selection should happen from runtime context and available provider
credentials first.

If explicit provider flags become necessary later, they should be added only
after the default CI detection story is clear.

## 13. Phased Implementation

### Phase 1: Review Provider Extraction

- extract GitLab review transport behind a provider-neutral review seam
- reduce direct GitLab dependencies in `ReviewRunner`
- keep behavior unchanged on GitLab

### Phase 2: GitHub Review Summary Support

- support GitHub PR intake from CI context
- build provider-neutral review context
- publish deterministic GitHub PR summary comments
- support same-SHA review reuse and prior-summary lookup

### Phase 3: GitHub Review Continuity And Inline Comments

- load prior GitHub review summaries into bounded continuity context
- preserve current continuity contracts
- later add GitHub inline comments with the same trust rules

### Phase 4: GitHub Remediation Publish Support

- support GitHub branch + PR publication for remediation
- keep the existing remediation execution core intact where possible
- do not assume GitLab MR-specific publication semantics

### Phase 5: GitHub Control Plane Design And Implementation

- design the GitHub-native work queue / dashboard-equivalent surface
- design operator control and policy interaction on GitHub
- connect remediation and review status back into that surface

### Phase 6: Full GitHub Dogfooding

- use ZeroOne Ops on this repository through GitHub-native review first
- expand into broader GitHub-native workflow usage as the control plane matures
- collect direct product feedback from real maintainer use

## 14. Main Risks

### 14.1 Shallow Parity

Risk:

- shipping “GitHub support” that really means only one narrow slice, while the
  product messaging implies much more

Mitigation:

- keep phase labels explicit
- do not present early slices as full parity

### 14.2 Bad Abstractions

Risk:

- hiding real GitLab/GitHub differences behind a fake generic API

Mitigation:

- make provider-neutral cores explicit
- keep provider-specific surfaces explicit where semantics differ

### 14.3 GitLab-Shape Lock-In

Risk:

- waiting too long makes more GitLab assumptions hard to undo

Mitigation:

- start the provider extraction sooner
- especially in the review flow where the core is already relatively portable

### 14.4 Platform Scope Creep

Risk:

- trying to deliver review, remediation, dashboard, and operator policy parity
  all at once

Mitigation:

- commit to the broader platform direction
- but still phase implementation carefully

## 15. Recommendation

GitHub support should be treated as a serious product platform expansion.

The right posture is:

- yes to the broader GitHub platform direction
- no to rushing it
- yes to early provider extraction work
- no to shallow “parity” claims before the control-plane and remediation story
  are real

The first implemented slice should still be GitHub review, because that is the
most portable current workflow and the fastest route to direct dogfooding.

But the design and planning frame should be broader:

- GitHub as a first-class ZeroOne Ops platform,
- with review first, not review only.
