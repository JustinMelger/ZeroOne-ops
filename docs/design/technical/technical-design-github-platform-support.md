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

Locked direction:

- Phase 5 should use a hybrid GitHub-native control plane.
- Phase 5a should start with one dedicated policy issue for repository-wide
  operator policy.
- authoritative state should live on normal GitHub objects:
  - issue labels and state
  - pull-request labels and state
  - explicit issue/PR linkage
- remediation issues and remediation pull requests should carry item-level
  execution truth.
- no persistent summary issue should be required in the first slice.
- any later persistent summary surface should be derived and read-only rather
  than the primary source of truth.
- operator actions in the first slice should prefer native GitHub state changes
  such as labels and close/reopen rather than markdown parsing or comment
  command dependence.
- review and remediation status should flow back into any later summary surface
  only as a concise mirror of the authoritative GitHub objects.
- the shared codebase should model this as one provider-neutral control-plane
  state domain rather than one universal dashboard surface.
- provider-local adapters should own:
  - authoritative policy storage
  - authoritative work-item / change-request state storage
  - optional rendered overview publication
- shared orchestration should depend on control-plane capabilities and state,
  not on GitLab dashboard markdown semantics.
- the control plane should stay producer-neutral:
  - raw producer findings are candidate inputs
  - not every candidate should become a first-class GitHub work item
  - only promoted work items should be materialized as authoritative GitHub
    control-plane objects
- this same boundary should keep current provider surfaces replaceable:
  - the GitLab dashboard should remain one provider-local implementation
  - the GitHub hybrid control plane should remain one provider-local
    implementation
  - a future external app should be able to adopt the same shared control-plane
    state model without rewriting shared orchestration
- naming should gradually move toward `control_plane`, `policy`, `work_queue`,
  and `overview` for shared concepts, while `dashboard` remains a provider-local
  GitLab implementation term where appropriate.

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
- completed provider-neutrality sweep across non-provider packages:
  - neutralized shared `merge_request_*` model, state, and traceability fields
  - kept genuinely shared contracts neutral while preserving provider-local
    publication semantics where they differ
- Phase 4 scope is complete for GitHub remediation publish support
- continue live GitHub validation under rollout rather than leaving Phase 4
  open for control-plane concerns

### Phase 5: GitHub Control Plane

- keep one shared control-plane state domain with provider-local storage/view
  adapters

#### Phase 5a: GitHub Policy Surface

- start with one dedicated policy issue for repository-wide operator policy
- define the bounded operator-editable policy shape on GitHub
- keep the policy issue authoritative for repo-wide policy only
- start with strict `issue_comment` commands on the policy issue as the first
  operator write path
- support bounded repo-wide policy mutations for:
  - severity enable/disable
  - issue-class exclude/include
- defer `/zeroone policy show|inspect` in the first GitHub slice
- replay accepted commands into canonical structured policy state
- keep rendered issue body state derived from structured policy instead of
  treating free-form markdown edits as authoritative
- discover the policy issue by:
  - canonical title `ZeroOne Ops Policy`
  - dedicated identifying label `zeroone-policy`
  - create-on-demand when missing
  - fail clearly on ambiguous multiple matches rather than guessing
- authorize policy commands through GitHub-native repository permissions rather
  than a config-managed username allowlist
- require `admin` repository authority for accepted policy commands in the
  first slice
- reuse the current strict `/zeroone policy` command grammar in the first
  GitHub slice rather than inventing a second policy syntax
- reuse the current GitLab policy semantics in the first GitHub slice:
  - severity enable/disable
  - issue-class exclude/include
- do not reuse the full GitLab dashboard policy rendering literally; keep the
  GitHub policy issue body as a smaller provider-local rendering of the same
  underlying policy state
- process policy comments through a dedicated workflow boundary rather than
  coupling policy mutation to remediation or review runs
- keep the first implementation stateless and idempotent:
  - replay the bounded accepted policy comments on every policy run
  - sort deterministically and let the latest valid command win for one target
  - do not add processed-comment cursors in the first slice
- keep acknowledgement optional in the first slice:
  - policy mutation should not depend on reply comments to function
  - do not post reply comments for malformed or unauthorized commands in the
    first slice
  - keep malformed/rejected/unauthorized command visibility in logs and metrics
    only
  - later acknowledgement UX can remain follow-up work
- keep the first rendered policy issue body compact and machine-owned:
  - header explaining the issue purpose and that direct body edits are not
    authoritative
  - current severity policy table
  - current issue-class exclusions table or an explicit empty-state line
  - exact supported command reference with examples
  - short notes covering authorization and machine-rendered status
- do not include grouped backlog inventory or broader overview content in the
  first policy issue body

#### Phase 5a Repo Design Pass

Small-layout outcome:

- do not start Phase 5a by moving the full GitLab dashboard domain into a new
  package tree
- do not place new GitHub policy logic directly under the existing
  `services/dashboard/*` package unless the logic is explicitly GitLab-dashboard
  specific

Recommended minimum structure:

- shared provider-neutral policy state and orchestration should move toward a
  small `control_plane` or `policy` area
- GitLab dashboard rendering and parsing should remain provider-local for now
- GitHub policy issue transport should land in provider-local code rather than
  in the shared dashboard package

Recommended first implementation seams:

- shared domain/state:
  - provider-neutral policy state model
  - provider-neutral policy command/action model
  - policy replay/orchestration service
- provider-local adapters:
  - GitLab dashboard policy note transport and rendered dashboard view
  - GitHub policy issue comment transport and rendered policy issue view

Recommended first package direction:

- keep existing GitLab dashboard services in place for now
- extract only the pieces that are already genuinely shared:
  - policy action grammar and typed actions
  - canonical policy state application/replay
- add GitHub policy-issue-specific code in provider-local modules instead of
  expanding the dashboard package with GitHub-specific transport concerns

Guardrail:

- `dashboard` should remain a provider-local GitLab implementation term
- new Phase 5a shared code should prefer names like `control_plane`, `policy`,
  and `overview`
- broader repo cleanup can follow once Phase 5a proves the seam shape in code
- keep the policy issue body machine-owned for canonical rendered state and
  operator guidance, not as a free-form editable contract
- keep provider markdown and provider comments as transport/projection only:
  - shared business rules should operate on structured policy state, typed
    policy actions, and replay/application services
  - GitHub issue bodies, issue comments, and GitLab dashboard markdown should
    not become the real domain model
  - no shared control-plane rule should depend on markdown layout details to
    remain correct
- keep the Phase 5a seams compatible with a later API/database control plane:
  - provider-backed control surfaces are the first storage adapters, not the
    final architecture
  - shared orchestration should be able to swap a provider-backed adapter for a
    database/API-backed adapter without changing policy semantics
  - rendering the GitHub policy issue or GitLab dashboard should stay a
    projection step over authoritative structured state

#### Phase 5b: GitHub Work-Item Control Plane

- keep remediation issues, pull requests, labels, and state transitions
  authoritative
- define item-level lifecycle and issue/PR linkage
- design operator control interaction on the authoritative item surfaces
- define the promotion rule from producer candidate to GitHub work item
- implement the first promotion rule as shared control-plane domain logic, not
  provider-local GitHub transport logic
- do not materialize every raw producer finding as a GitHub issue
- keep GitHub work-item volume bounded across multiple producers
- current lean: treat operator relevance as a coordination threshold rather than
  a producer or severity threshold
- keep all producer candidates visible through aggregated inventory even when
  they are not promoted into first-class GitHub work items
- lock the first authoritative GitHub work-item shape as one GitHub issue
- treat the remediation pull request as linked execution state, not as the
  primary work-item record
- keep the shared domain neutral and avoid dashboard-shaped names in this phase;
  prefer names like `WorkItem`, `WorkItemStatus`, and `ChangeRequestRef`
- use one bounded machine-readable issue block for the authoritative contract;
  labels remain filter and status signals, not the full data contract
- require the first work-item issue payload to carry at least:
  - `work_item_id`
  - `source`
  - `source_item_key`
  - `kind`
  - `status`
  - `severity`
  - optional linked change-request reference
  - created-by-system marker
- lock the first shared status set to:
  - `candidate`
  - `approved`
  - `in_progress`
  - `blocked`
  - `completed`
  - `dismissed`
- promote a candidate into a GitHub work item only when it needs durable shared
  coordination in the first slice, specifically when it:
  - is selected for remediation
  - becomes blocked and needs human attention
  - is linked to an open remediation pull request
- do not promote retry-eligible items by default in the first slice
- keep non-promoted backlog visibility aggregate-only in `5b.1`:
  - derived counts or grouped summary are allowed
  - no second authoritative per-item surface is allowed outside promoted
    GitHub work-item issues
- keep the first operator control surface label- and state-driven on the
  authoritative issue; do not add comment-command mutation on work items yet
- keep the first work-item entry path bot-created only; operator-authored
  work-item issue intake can follow after the issue contract is proven stable
- lock linkage to zero or one active remediation pull request per work item
- if a linked remediation pull request closes unmerged, move the work item back
  to `approved` or `blocked` based on the failure outcome rather than keeping
  the pull request as the source of truth
- narrow the first implementation slice to:
  - shared work-item domain models
  - shared remediation work-item promotion decision service
  - provider-local GitHub work-item issue renderer and parser
  - bot-created promoted work items only
  - one linked remediation pull-request reference
  - minimal status and label mapping
  - no operator-created work items yet
  - no derived summary issue
  - no comment-command surface on work items
  - no fake generic adapter that hides real GitHub/GitLab transport differences

##### Phase 5b.1 Invariants

Promotion-decision contract:

- the first shared promotion service must evaluate normalized
  `RemediationWorkItem` candidates rather than raw dashboard items or already
  selected execution targets
- the first service contract should stay narrow:
  - input: one normalized remediation work item plus bounded promotion context
  - output: `promote` or `backlog_only` plus one stable reason
- the first bounded promotion context should include only:
  - `selected_for_remediation`
  - `blocked_requires_attention`
  - `linked_change_request_open`
- do not include provider-local GitHub flags, severity thresholds, or summary
  rendering fields in the first shared promotion contract
- the first reason set should stay bounded to:
  - `selected_for_remediation`
  - `blocked_requires_attention`
  - `linked_change_request_open`
  - `default_backlog_only`
- when multiple promotion triggers are true, use stable precedence so tests and
  later summaries remain deterministic:
  - `selected_for_remediation`
  - `blocked_requires_attention`
  - `linked_change_request_open`
- the first consumer of this decision should be the candidate-to-GitHub
  work-item materialization boundary, not the publish path, because publish is
  already a promoted execution path

Status ownership:

- the canonical source of truth for one GitHub work item must be the
  machine-readable state block in the authoritative work-item issue body
- that state must retain the bounded provider-neutral `remediation_context`
  needed by shared execution, including category, diagnostic code, validation
  commands, and optional fix constraints
- raw source metadata must remain outside authoritative work-item state
- GitHub labels must be projections of canonical work-item state and must not
  become the primary source of truth
- remediation pull-request state is linked execution evidence, not canonical
  work-item state by itself
- any local persisted state remains a cache and must be reconstructable from
  authoritative GitHub objects

Identity and reuse:

- `work_item_id` must be system-generated and stable for the life of one
  created work item
- reuse matching must be based on stable identity fields from canonical state,
  not on issue title text or incidental labels
- the first reuse key should be provider-neutral source identity plus
  work-item kind
- if an open work item already exists for the same canonical identity, reuse it
- if only closed matching work items exist, create a new work item in `5b.1`
  rather than reopening by default
- reopening closed matching work items can be added later only as an explicit
  policy with tests

Label projection:

- labels are an operator-facing projection layer and must remain derivable from
  canonical work-item state
- shared orchestration must not branch on raw GitHub label text as domain logic
- provider-local GitHub code may map canonical status and flags onto labels, but
  shared services must depend on structured work-item state instead

Linked pull-request transitions:

- one work item may have zero or one active remediation pull request
- a remediation pull request must link back to its authoritative work-item issue
- the authoritative work-item issue must carry the current linked pull-request
  reference when one exists
- if a linked remediation pull request merges successfully, the work item moves
  to `completed`
- if a linked remediation pull request closes unmerged, the work item must move
  to `candidate` with its linked pull-request reference cleared; a later
  complete finding-sync pass may promote it again only when the finding remains
  active and policy-eligible
- lifecycle reconciliation must not run source tools or depend on a previous
  GitHub Actions artifact: it can always converge open and merged pull requests
  from the stored link, while finding sync remains authoritative for fresh
  source inventory and re-promotion

##### Phase 5b.1 Locked Defaults

Failure classification on unmerged pull-request close:

- if a remediation pull request is closed unmerged after validation or fix
  generation failure, move the work item to `blocked`
- if a remediation pull request is closed unmerged because publication failed
  after branch push or another transport-side failure prevented a clean
  remediation handoff, move the work item to `blocked`
- if a remediation pull request is manually closed by an operator without
  signaling that the work item is permanently dismissed, move the work item
  to `candidate` and clear its pull-request link
- the next complete finding-sync pass may promote that `candidate` item to
  `approved` only when the finding remains active and is currently
  policy-eligible; it otherwise remains non-executable
- if a remediation pull request is superseded by a newer remediation pull
  request for the same work item, keep the work item active and linked to the
  newer pull request rather than treating the old close as terminal

Work-item kind set:

- lock `5b.1` to a single kind: remediation work item
- do not generalize kind-specific behavior until a second real work-item kind
  exists in code

Source identity normalization:

- define the first provider-neutral source identity from:
  - producer source name
  - producer-stable item key
  - repository scope when needed by the producer
- for Sonar-derived work, the stable source key should use the Sonar issue key
  rather than mutable presentation fields such as title text or severity labels
- branch names, issue titles, and rendered issue bodies must not participate in
  the canonical reuse key

Work-item title rendering:

- titles are provider-local display output only and are not authoritative for
  reuse or identity
- the first GitHub work-item title should stay compact and consistent:
  - fixed prefix identifying ZeroOne Ops ownership
  - short human summary of the remediation target
  - no machine-only identifiers in the visible title unless needed for operator
    disambiguation

Minimal label set:

- keep the first GitHub label set intentionally small
- the first slice should map canonical work-item state onto only the minimum
  operational labels:
  - one ownership label for ZeroOne Ops-managed work items
  - one status label derived from canonical work-item status
  - optional producer label when it materially helps operator filtering
- do not encode full business logic in labels and do not require labels for any
  field already present in canonical work-item state

Creation timing:

- create or update the authoritative GitHub work-item issue at the moment a
  candidate is promoted into durable coordination state
- do not wait for remediation pull-request creation to succeed before creating
  the work item
- after pull-request creation succeeds, update the authoritative work item with
  the linked pull-request reference
- this keeps failure reporting visible even when remediation execution does not
  reach successful pull-request publication

#### Phase 5c: GitHub Status Projection

- connect remediation and review workflow status back into the GitHub control
  plane
- project shared workflow state onto authoritative GitHub objects without
  making rendered markdown authoritative
- keep review projection as concise status and traceability only
- do not mirror full review-note content into the control plane
- keep the review note/comment as the primary human-facing review surface

Locked workflow baseline:

- follow the GitLab implementation at the workflow-rule level:
  - remediation lifecycle remains the primary workflow state
  - review projection is secondary status and traceability
  - human-facing review prose is never authoritative control-plane state
- do not copy the GitLab dashboard storage shape into GitHub
- implement the same workflow semantics through provider-local GitHub storage
  and rendering

Locked first-slice storage boundary:

- project review status only onto an already-promoted authoritative GitHub work
  item
- do not create a new GitHub work item from review projection alone in `5c`
- if no promoted work item exists for the reviewed change, do not project
  review state into the control plane
- keep the review note/comment as the only GitHub surface in that case

Locked first-slice projected fields:

- use shared review classification semantics rather than introducing a new
  GitHub-only vocabulary:
  - `no_findings`
  - `findings_present`
  - `manual_review_only`
- store only bounded review traceability and follow-up state on the
  authoritative work item:
  - projected review classification
  - reviewed SHA
  - latest review note URL
  - compact follow-up-needed flag derived from the classification
- do not copy finding prose, summaries, evidence, or suggested fixes into the
  authoritative control-plane state

Locked rendering shape:

- render projected review state as one small machine-owned section inside the
  authoritative GitHub work-item issue body
- keep that section compact and deterministic:
  - projected review classification
  - reviewed SHA
  - latest review note URL
  - follow-up-needed flag
- do not duplicate the human review note body or the inline review findings in
  that section
- treat the rendered section as a provider-local projection over structured
  state rather than as the canonical source of truth

Locked update timing and precedence:

- update GitHub review projection only after a review run has completed and a
  publishable review result exists
- remediation lifecycle remains primary:
  - review projection must not overwrite remediation execution state such as
    `approved`, `in_progress`, `blocked`, `completed`, or `dismissed`
- review projection may update only review-specific metadata and
  follow-up-needed state on the authoritative work item
- latest successful projected review result wins for review metadata fields
  without rewriting unrelated remediation traceability

Out of scope for `5c`:

- developer reply or emoji feedback loops on review comments
- creating work items from repo-wide review results that have no promoted
  remediation item
- mirroring full review output into the control plane
- derived overview publication beyond the existing authoritative work-item
  issue

#### Phase 5d: Optional Derived Overview

- do not require a persistent summary issue in the first slice
- allow a persistent summary issue later only as a derived visibility layer
- add a summary surface only if operator usage proves native GitHub views are
  insufficient

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

Locked direction:

- Phase 4 should aim for functional parity with the current GitLab remediation
  publish flow rather than a reduced GitHub-only variant.
- parity should be defined at the workflow-outcome level:
  - create or reuse a remediation change request
  - publish from the remediation branch to the configured target branch
  - persist branch, commit, and change-request traceability
  - surface publish success or failure back into shared state and summaries
  - support retry-safe behavior around existing open remediation change requests
- implementation details may still remain provider-local where GitHub and
  GitLab semantics differ.
- Phase 4 should not pull GitHub control-plane concerns into remediation
  publish; those belong to Phase 5.

Locked Phase 4 behavior rules:

- reuse only open remediation change requests for the same source branch and
  target branch pair
- do not reuse closed remediation change requests, even if the branch still
  exists remotely
- support labels in Phase 4 where the provider allows them
- support assignee mapping only where the provider mapping is straightforward;
  reviewer-specific flows can remain a later concern
- keep the pushed remediation branch in place if change-request publication
  fails after push, and report the failure clearly instead of attempting
  rollback cleanup
- preserve `created` versus `reused` publication outcomes consistently across
  GitLab and GitHub

### 16.7 GitHub Control Plane Direction

Primary phases:

- Phase 5: GitHub Control Plane
- Phase 5a: GitHub Policy Surface
- Phase 5b: GitHub Work-Item Control Plane
- Phase 5c: GitHub Status Projection
- Phase 5d: Optional Derived Overview
- Phase 6: GitHub Platform Rollout

What should the GitHub-native work-queue / control-plane shape be?

Locked answer:

- use a hybrid control plane
- start with one dedicated policy issue for repository-wide operator policy
- keep remediation issues, pull requests, labels, and state transitions as the
  authoritative execution surface
- do not require a persistent summary issue in the first slice
- allow a persistent summary issue later only as a derived visibility layer
- do not make machine-managed summary markdown the primary source of truth

Why:

- it preserves GitHub-native operator ergonomics
- it avoids rebuilding the GitLab dashboard too literally on a weaker surface
- it keeps automation boundaries clear between durable state and rendered
  visibility

### 16.8 Provider-Neutral Remediation Runner

Primary phase:

- Phase 6c4: Provider-Neutral Remediation Runner

How should GitHub work items enter the existing remediation execution flow
without extending the GitLab dashboard runner into a false-neutral abstraction?

Locked direction:

- add `zeroone-ops remediation run` as the canonical provider-neutral command
- retain `zeroone-ops dashboard remediate` as a GitLab compatibility alias
- keep `DashboardItemIntakeService` and `DashboardRemediationRunner` explicitly
  GitLab-local
- add a GitHub-local work-item intake and runner that selects one authoritative
  GitHub work item and produces the shared `RemediationExecutionTarget`
- route both provider-local runners through the existing shared
  `ExecutionService`, branch/PR publication path, and result handling
- move shared run-summary vocabulary from `dashboard_item_id` toward
  `work_item_id`; provider-local dashboard or issue references remain separate

Locked operational defaults:

- process at most one eligible `approved` work item per run, ordered by
  normalized severity (`high`, `medium`, `low`), then GitHub issue creation
  time, then issue number as a deterministic tie-breaker
- claim the selected GitHub work item as `in_progress` before execution
- expose remediation first through a `workflow_dispatch` GitHub Actions
  entrypoint with repository-wide concurrency
- add a scheduled entrypoint only after one manual live remediation run has
  completed successfully
- do not execute remediation directly from issue comments; comments remain a
  policy/control interaction surface
- project execution results back to the authoritative GitHub work-item state;
  preserve the existing linked pull-request reconciliation rules

Claim serialization rule:

- GitHub Issue updates do not provide a compare-and-swap claim primitive for
  this workflow, so repository-wide GitHub Actions concurrency is the
  authoritative claim-serialization boundary for live remediation
- every live GitHub remediation entrypoint must use the same repository-scoped
  concurrency group with `cancel-in-progress: false`
- do not enable scheduled or manual live remediation until that workflow-level
  serialization is in place; local runs remain dry-run only
- do not automatically close native GitHub issues in this phase
- do not automatically retry `blocked` work items; a later explicit operator
  action may return one to `approved`, while the first runner leaves blocked
  items untouched

Future claim hardening:

- GitHub Actions concurrency is sufficient only while every live remediation
  run is dispatched through the shared repository-scoped workflow group
- before supporting external schedulers, local live execution, or multiple
  independent workers, move work-item claiming to a persistent versioned store
  or provider boundary with an atomic compare-and-set operation
- do not treat an additional read-before-write eligibility check as an atomic
  claim fix; it preserves the same race

Implementation order:

1. add the neutral command, runner entrypoint, and shared run-summary vocabulary
2. add GitHub work-item selection, claiming, and normalization
3. connect shared execution and provider-local GitHub lifecycle projection
4. add workflow entrypoints and live-test one Ruff-derived work item through
   pull-request publication and reconciliation
