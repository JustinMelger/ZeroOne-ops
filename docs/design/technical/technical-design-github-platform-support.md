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

- `providers/review/gitlab.py`
- `services/review/intake/change_request_intake.py`
- `services/review/review_gitlab_prior_context_service.py`
- `services/review/review_gitlab_prior_note_parser.py`
- `services/review/publish/review_publisher.py`
- `services/review/pipeline/review_runner.py`

Since this design started, the shared review code has been regrouped into:

- `services/review/intake/`
- `services/review/context/`
- `services/review/continuity/`
- `services/review/publish/`
- `services/review/pipeline/`
- `services/review/state/`
- `providers/review/`

That package cleanup is completed `Phase 2b` structural work and gives the
GitHub slices a cleaner domain map to build on.

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

Design rule for later GitHub phases:

- every new GitHub feature must explicitly justify whether it belongs in
  shared review-domain logic or in provider-local code
- if the behavior is part of the product review contract, keep it in shared
  review-domain logic
- if the behavior exists because GitHub's API, CI surface, or publication
  model differs, keep it provider-local
- do not solve provider quirks by adding ad hoc GitHub special cases to the
  shared review runner or core review services

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

### 6.4 Phase 1 Seam Rule

Phase 1 should follow one practical extraction rule:

- if `ReviewRunner` is currently coupled to GitLab through a specific
  responsibility, that responsibility should move behind a provider-neutral
  seam

This keeps Phase 1 grounded in real coupling rather than speculative
abstraction.

Likely first-pass seams include:

- intake / pull-request fetch
- current PR/MR state lookup
- prior-review continuity loading
- authoritative summary publication
- inline-comment publication
- bot author identity lookup

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

### 8.1 Introduce Smaller Review Provider Seams

The platform docs suggest GitHub and GitLab diverge enough that one broad
review client would likely become awkward too quickly.

GitHub separates:

- pull request resources,
- issue comments on pull requests,
- pull request reviews,
- pull request review comments,

while GitLab is closer to:

- merge request resources,
- merge request notes,
- merge request discussions.

So the design should prefer smaller provider-facing seams, for example:

- intake and diff fetch
- summary-surface publication
- inline-comment publication
- prior-review continuity loading
- author identity lookup

This should age better than forcing every provider concern into one broad
`ReviewPlatformClient` too early.

### 8.2 Move Toward Provider-Neutral Review Naming

Current names like:

- `MergeRequestReviewCandidate`
- `MergeRequestReviewContext`
- `MergeRequestChangedFile`

should evolve toward provider-neutral review naming, for example:

- `ChangeRequestReviewCandidate`
- `ChangeRequestReviewContext`
- `ChangeRequestChangedFile`

The design direction should be explicit:

- perform this provider-neutral rename during Phase 1

Reason:

- these models sit close enough to the review core that keeping GitLab-shaped
  names during GitHub support would encourage the wrong mental model and make
  later provider-neutral boundaries harder to keep clean.

Naming rule:

- choose names from the review domain itself, not from the current provider and
  not from the next provider

That means the Phase 1 rename should aim for the most neutral
domain-oriented vocabulary we can justify, so later platform work is not
shaped by leftover GitLab or GitHub terminology.

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

Chosen first transport:

- GitHub pull request issue comment

Reason:

- every pull request is also an issue in GitHub’s API model
- issue comments are a simpler and more stable authoritative summary surface
  than pull request review objects for our continuity and same-SHA reuse model
- this keeps the first GitHub summary surface closer in spirit to the current
  GitLab merge request note model

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

For GitHub Actions pull request workflows, same-SHA continuity should not rely
on `GITHUB_SHA` alone.

The platform docs show that:

- `GITHUB_REF` points at the pull request merge ref for `pull_request`
  workflows
- `GITHUB_HEAD_REF` and `GITHUB_BASE_REF` describe source and target branches
- `GITHUB_EVENT_PATH` contains the full event webhook payload

So GitHub review continuity should recover the authoritative head SHA from the
event payload and/or pull request API data rather than assuming the default
workflow SHA is the authoritative review head identity.

If explicit provider flags become necessary later, they should be added only
after the default CI detection story is clear.

## 13. Phased Implementation

### Phase 1: Review Provider Extraction

- extract GitLab review transport behind a provider-neutral review seam
- rename GitLab-shaped review models to provider-neutral pull-request naming up
  front
- reduce direct GitLab dependencies in `ReviewRunner`
- keep behavior unchanged on GitLab
- merge and live-validate GitLab review stability before starting Phase 2

### Phase 2: GitHub Review Summary Support

- support GitHub PR intake from CI context
- build provider-neutral review context
- publish deterministic GitHub PR summary comments
- support same-SHA review reuse and prior-summary lookup

### Phase 3: GitHub Review Continuity And Inline Comments

- load prior GitHub review summaries into bounded continuity context
- preserve current continuity contracts
- later add GitHub inline comments with the same trust rules
- add provider-backed GitHub inline-thread state observation only for transport
  behavior, not as a replacement for authoritative summary continuity
- if a developer resolved an earlier GitHub inline thread, later runs should
  default to summary-only transport unless a new explicit re-publication rule
  is justified

### Phase 4: GitHub Remediation Publish Support

- support GitHub branch + PR publication for remediation
- keep the existing remediation execution core intact where possible
- do not assume GitLab MR-specific publication semantics
- completed Phase 4a config-prep slice:
  - moved repo provider selection to top-level `platform`
  - moved remediation publication targeting to shared `remediation.target_branch`
  - kept provider-local publication metadata explicit under provider blocks
- completed shared publish seam slices:
  - extracted remediation publish behind a provider-local change-request
    publisher seam
  - extracted dashboard active-change-request lookup behind a provider-local
    lookup seam
- next slice:
  - neutralize shared `merge_request_*` model, state, and traceability fields
- do one strict provider-neutrality sweep across non-provider packages before
  GitHub remediation publish lands
- move only genuinely shared contracts into neutral surfaces
- keep provider-local publication semantics explicit where they differ

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

## 16. Open Questions

These questions do not block Phase 1, but they should stay visible in the
design so later implementation slices do not guess silently.

### 16.1 Review Provider Seam Shape

Primary phase:

- Phase 1: Review Provider Extraction

- smaller provider-facing seams for intake/fetch, prior-review continuity, and
  publication

Current design direction:

- prefer smaller provider-facing seams

Reason:

- docs-backed API differences between GitHub and GitLab already suggest that
  one broad client would hide too many transport differences too early.

### 16.2 Provider-Neutral Model Rename Timing

Primary phase:

- Phase 1: Review Provider Extraction

Should GitLab-shaped model names such as:

- `MergeRequestReviewCandidate`
- `MergeRequestReviewContext`

be renamed up front before GitHub support lands, or should adapters be added
first and the rename happen later?

Chosen design direction:

- rename up front during Phase 1

Reason:

- this avoids GitLab-shaped naming leakage in the first GitHub implementation
  slice
- it keeps the review core mentally and structurally cleaner before provider
  expansion begins

### 16.3 GitHub Authoritative Summary Surface

Primary phase:

- Phase 2: GitHub Review Summary Support

Chosen design direction:

- GitHub pull request issue comment

Reason:

- it is the closest stable equivalent to the current authoritative GitLab merge
  request note
- it avoids coupling first-pass continuity to GitHub review-object lifecycle
  semantics
- it keeps inline review comments clearly subordinate

### 16.4 GitHub Same-SHA Continuity Lookup Contract

Primary phases:

- Phase 2: GitHub Review Summary Support
- Phase 3: GitHub Review Inline Comments

The obvious identity is:

- repository identity
- pull request number
- head SHA

Docs-backed constraint:

- do not rely on `GITHUB_SHA` alone in GitHub Actions pull request workflows

Chosen design direction:

- recover authoritative head identity from the GitHub event payload and/or pull
  request API data before continuity lookup
- use the event payload first, but prefer live pull request API head state when
  both are available
- use the GitHub pull request head SHA as the authoritative reviewed revision
  identity
- treat `GITHUB_SHA` as diagnostic workflow context only, not the authoritative
  continuity identity
- reuse a prior authoritative summary only on an exact match of:
  - repository identity
  - pull request number
  - pull request head SHA
- if workflow context and pull request API state disagree, prefer the pull
  request event/API head SHA, log the mismatch, and continue conservatively
  without risky summary reuse on ambiguous identity
- if more than one bot-authored machine-parseable authoritative summary exists
  for the exact same reviewed revision, prefer the newest matching summary and
  warn about duplicates
- require bot-authored identification through an explicit machine-safe marker
  plus parseable payload rather than actor name alone
- reuse the current provider-neutral machine-safe payload structure as much as
  possible rather than inventing a GitHub-specific payload shape in Phase 2

Reason:

- false reuse is worse than missed reuse during early GitHub rollout
- GitHub Actions pull request workflow SHA values can represent merge refs or
  workflow-trigger context rather than the exact reviewed head revision
- strict reuse keeps continuity trustworthy while still allowing tolerant
  diagnostics when workflow context drifts

### 16.5 GitHub Review Config Neutralization

Primary phase:

- Phase 2b: GitHub Review Config And Documentation Cleanup

Problem:

- the first GitHub summary-support implementation relied on a required
  top-level `gitlab` config block even when `platform=github`
- that was acceptable for an internal implementation checkpoint, but it was
  not an honest long-term review configuration contract

Chosen design direction:

- introduce a provider-neutral review configuration surface for shared review
  behavior
- keep true GitLab provider connection/runtime configuration provider-local
- support legacy GitLab review input during a transition period by normalizing
  old GitLab-shaped review fields into the neutral review config at load time
- do not use Phase 2b to fully neutralize remediation or control-plane config;
  scope it to the review workflow contract

Implemented Phase 2b config outcome:

- GitHub review mode no longer requires a dummy top-level `gitlab` block
- repo-level platform selection stays under top-level `platform`
- provider-local GitLab workflow settings remain available for GitLab-backed
  remediation and dashboard paths that still require them
- review-domain packaging should be tightened where Phase 1 and Phase 2 left
  review logic spread across loosely grouped modules; Phase 2b should group
  related review-platform, intake, publish, and prior-comment concerns under
  clearer review-focused package boundaries before Phase 3 grows on top of them
- the target package map for that cleanup is defined in
  `technical-design-review-package-layout.md`
- the review integration test suite now mirrors the cleaned package map instead
  of growing further under one broad integration file
- the migration path from legacy GitLab review config is now documented in the
  design docs, runbook, and config examples

Reason:

- the product contract should match the provider-neutral review architecture
  already extracted in Phase 1
- GitHub summary support is not really complete if GitHub-only repositories
  still need GitLab-shaped config to start the review runner
- Phase 2 already increased the number of review-adjacent files touched for one
  provider feature, so packaging cleanup now is cheaper and safer than letting
  GitHub review grow on top of a scattered module layout
- a bounded transition period is safer than a hard config break while GitLab
  remains the mature production path

### 16.6 Remediation Publish Reuse Boundary

Primary phase:

- Phase 4: GitHub Remediation Publish Support

How much of the current remediation publish path is genuinely provider-neutral,
and how much should be extracted behind a dedicated branch/PR publication seam
before GitHub remediation support starts?

### 16.7 GitHub Control Plane Direction

Primary phases:

- Phase 5: GitHub Control Plane Design And Implementation
- Phase 6: GitHub Platform Rollout

What should the GitHub-native work-queue / control-plane shape be?

Possible directions:

- one persistent issue similar to the current GitLab dashboard
- a label and issue/PR state driven workflow
- another lighter GitHub-native control surface

This is the biggest later product-design question and should not be answered by
accident through transport reuse alone.
