# Future Plans

## Shared Engine With Specialized Sources

Evolve the project from a SonarQube-only bot into a shared code-fix automation
engine with specialized work-item sources.

Working platform direction:

- current platform name: `ZeroOne Ops`
- current implementation already includes Sonar remediation, PR review, and
  dashboard sync on GitLab
- remediation scope remains SonarQube-first for now
- keep runtime compatibility names pragmatic until a later dedicated rename
  phase

Potential later bot naming set to evaluate carefully:

- remediation bot: `Sentinel`
- review bot: `Oracle`
- dashboard sync bot: `Link`
- reconciliation bot: `Architect`

Naming guidance if this direction is used:

- keep CLI and CI job names descriptive, even if the bots have platform names
- treat these as branding or product-surface names, not replacements for clear
  workflow terminology
- avoid committing to a full rebrand until the shared platform expands beyond
  the current SonarQube-first implementation

## Priority Expansion Tracks

These are the highest-value expansion directions for the current team setup on
self-hosted GitLab.

### 1. Pipeline Failure Bot

Goal:

- reduce engineering time spent diagnosing and fixing broken pipelines

Recommended v1 scope:

- ingest one failed pipeline job per run
- focus on failed test, lint, and typecheck jobs first
- collect failing command, logs, and target package or service
- attempt only low-risk fixes
- validate by rerunning the relevant checks locally before opening a merge request

Recommended architecture direction:

- split the pipeline path into discovery and remediation
- let a pipeline failure discovery bot monitor failed jobs
- normalize one actionable failure into a structured dashboard item
- let the generic fix bot consume that structured item instead of raw pipeline data

Stable-phase config direction for remediation scope:

- keep the current `supported_rules` allowlist during testing and early rollout
- later, consider a broader default support model with explicit exclusions such
  as `ignored_rules` or `excluded_rules`
- if both modes are ever supported, let explicit `supported_rules` keep strict
  allowlist behavior while exclusion-based config becomes the easier stable
  default

Why this shape is better:

- raw pipeline failures are noisy and inconsistent
- many failed jobs are not actually fixable by code changes
- the dashboard item becomes the stable contract between failure discovery and remediation
- the generic fix bot can later consume SonarQube issues, dashboard items, and ticket-based work in the same way

Recommended dashboard fields for pipeline-generated work items:

- `id`
- `source: pipeline_failure`
- `pipeline_id`
- `job_id`
- `job_name`
- `commit_sha`
- `branch`
- `summary`
- `failure_type`
- `log_excerpt`
- `expected_change`
- `validation_commands`
- `status`

Why first:

- pipeline failures are usually more structured than human-authored tickets
- the success criteria are clearer
- the operational pain is immediate and measurable
- later product refinements in this area could also:
  - trigger a focused bot note when a pipeline fails, with a concise summary,
    likely cause, and suggested next step
  - surface failing test names directly into the dashboard or failure note
  - detect likely flaky tests by tracking pass/fail instability across recent
    pipeline history instead of only summarizing one failed run

### 2. Security Scan Producers To Dashboard

Goal:

- bring findings from commonly used security scanners into the shared dashboard
  so security-oriented static analysis can use the same discovery and triage
  surface as other producers

Recommended later scope:

- prefer scanners that are common enough in real engineering teams to make
  dashboard ingestion operationally useful, such as Semgrep, Aikido, or other
  broadly adopted SAST/security platforms
- capture structured scanner output in CI
- normalize selected findings into strict dashboard items
- keep the first rollout discovery-only so operators can inspect signal quality
  before any remediation path is enabled

Recommended architecture direction:

- treat security scanners as producers that write structured dashboard work
  items
- keep the dashboard item as the stable contract between scanner discovery and
  any later remediation workflow
- only allow remediation later for a narrow allowlist of finding types after
  signal quality is proven

Recommended dashboard fields for security-scan-generated work items:

- `id`
- `source`
- `rule_id`
- `severity`
- `file`
- `line`
- `summary`
- `message`
- `status`

Why this shape is better:

- it reuses the same dashboard-first control plane already built for Sonar
- commonly used scanners are more likely to justify the ingestion and operator
  workflow cost
- security/static-analysis producers stay aligned with the shared work-item
  contract instead of becoming one-off workflows

### 2.5. Interactive Dashboard Policy Surface

Goal:

- evolve the dashboard from a mostly rendered status board into a stronger
  operator control surface
- keep the dashboard as the broader shared work inventory while letting
  operators shape what automation will actually pick up
- make exclusion and policy interaction part of the product rather than a
  hidden side configuration path

Why this direction is stronger:

- source-specific producers can sync normalized items without silently hiding
  classes of work
- operators keep visibility into what work exists even when automation should
  skip it
- remediation policy stays explicit at the consumer boundary where automation
  risk is actually accepted or rejected
- the same dashboard surface can later support more than one workflow or
  consumer

Recommended direction:

- keep the dashboard as the shared work inventory and control plane
- keep exclusions source-aware in identity, but remediation-owned in
  application
- let producer bots sync normalized items without applying operator exclusions
  during source sync
- make the remediation bot decide automated pickup eligibility from the
  synchronized dashboard inventory

Interactive dashboard direction:

- move beyond flat item lists toward grouped views by source and key where that
  improves operator decisions
- support grouped issue-class interactions such as:
  - exclude from automation
  - inspect current exclusion reason
  - review how many current items match that pattern
- use that grouped interaction model to make noisy issue classes easier to
  understand and manage

Examples of future grouped policy views:

- `sonarqube / python:S3776`
  - current item count
  - excluded from automation: yes/no
  - exclusion reason
  - last updated
- `pipeline_failure / mypy:arg-type`
  - current item count
  - excluded from automation: yes/no
  - exclusion reason
  - last updated

Why this needs deliberate design:

- doing this properly touches dashboard information architecture, not only one
  small remediation toggle
- the grouped and interactive dashboard model is larger than a narrow quick
  fix
- it is better to build this as a deliberate product step than as a side
  feature

Design reference:

- [technical-design-remediation-exclusions.md](docs/design/technical/technical-design-remediation-exclusions.md)
- [functional-design-dashboard-operator-policy.md](docs/design/functional/functional-design-dashboard-operator-policy.md)
- [technical-design-dashboard-operator-policy.md](docs/design/technical/technical-design-dashboard-operator-policy.md)

Guardrails:

- do not let operator exclusions silently weaken hard safety rules
- do not collapse the dashboard back into a hidden autofix-only queue
- do not make the first interactive policy model depend on free-form text
  parsing
- do not treat one repo's exclusions as universal platform truth

Possible later refinement:

- after repositories have migrated to `remediation.bootstrap_severities`,
  remove the legacy `supported_severities` compatibility path from config
  loading and operator docs
- if the dashboard policy command surface grows later, consider introducing a
  more explicit per-note policy outcome model so acknowledgement behavior does
  not have to infer increasing amounts of accepted/rejected/no-op detail from
  parse results alone
- do not evolve the dashboard interaction model without a clearer versioning and
  migration story for live dashboard state

Important implementation note:

- past dashboard format changes have broken live parsing badly enough that the
  only safe recovery was deleting and recreating the dashboard from scratch
- that may be acceptable for an early rendered-status board, but it is not a
  good fit once the dashboard becomes a richer operator-managed product surface
- before interactive policy controls are added, the dashboard direction should
  include explicit schema/version handling, more tolerant parsing where
  possible, and a migration or rewrite path for existing live boards
- recent live parse errors reinforce that dashboard summary/layout evolution is
  still too brittle; keep treating parser compatibility and live upgrade safety
  as an explicit hardening track, not an assumed property of new renderer work
- operator recovery from an unparsable dashboard still needs a clearer surfaced
  failure path, including explicit "rewrite skipped to avoid data loss"
  messaging and safer recovery guidance

Open questions for the later dashboard phase:

- what exact bounded transport should the first dashboard policy write path use
  for operator actions
- whether grouped policy should eventually support richer source-local grouping
  beyond the first `source + issue_key` model
- how much grouped dashboard detail is enough for operators before the view
  becomes noisy
- what dashboard schema/versioning and migration mechanism should support live
  upgrades without delete-and-recreate recovery

## MLflow Tracing Follow-On Directions

If the first narrow MLflow autologging slice proves useful, likely later
extensions include:

- add high-level manual spans around the review workflow
  - start with major stages such as candidate generation, precision review,
    reconciliation, and artifact building
  - keep the first implementation read-only from a workflow-behavior
    perspective
- attach bounded review metadata and tags
  - examples: MR IID, SHA, classification, findings count, same-SHA reuse
  - improve filtering without logging unnecessary repository content
- extend tracing to remediation later
  - likely stages: analysis, patch execution, validation, and publish
- decide whether and when a shared MLflow instance is worth supporting beyond
  local experimentation
  - document expected tracking URI / experiment setup if shared usage becomes
    normal
  - keep infra/setup decisions separate from the initial code-side tracing
    basis
- dashboard mirroring is additive and should not replace MR-first output

### Review Improvement Track

Recommended near-future focus:

- improve operator trust in the review bot before widening its role in the
  platform
- make review output more useful, evidence-backed, and lower-noise

High-value improvements:

- teach the review workflow to use remediation-authored MR context when it is
  available, while degrading gracefully for normal human-authored merge
  requests
- let developers explicitly disagree with a bot finding and store that as
  structured feedback so later review passes on the same MR can avoid
  re-reporting the same point as if it were still unresolved
- consider numbering review findings so developers can reply with short
  structured feedback such as `1. not an issue`, letting the bot acknowledge
  the response and avoid re-arguing that same finding on later passes of the
  same merge request
- suppress speculative or weak findings more aggressively so the bot prefers
  no-findings over noisy low-confidence output
- keep model-generated review confidence as the base signal, and only later
  consider bounded downward calibration from observable uncertainty such as
  broad diffs, many files touched, truncated context, or validation downgrades
- add a later performance-aware review mode for obvious redundant work, such
  as duplicate database calls, repeated fetching of already-available data, or
  heavy request-path work introduced when equivalent data is already loaded by
  existing helpers
- strengthen finding formatting so each review comment ties the risk to
  concrete diff evidence or nearby source context
- if review-context expansion is revisited, prefer bounded helper-following
  context before function-aware whole-function expansion, since current
  false-positive patterns are more often caused by missing helper/callee truth
  than by insufficient lines from the changed function alone
- improve branch attribution for review findings by adding better
  context/validation support, especially when a changed flow mirrors an
  existing unchanged sibling path; later options could include showing nearby
  sibling-path context in the review packet or adding a lightweight
  post-review check for "is this pattern already present in an unchanged
  nearby path?"
- make manual-review-only outcomes clearer so operators can distinguish
  insufficient context from low-value findings
- add repo-level controls for review noise such as path filtering,
  changed-file limits, and note verbosity
- make repository-guidance discovery configurable so repositories can point
  review and remediation at different guidance files or locations without
  weakening the untrusted-input boundary
- if review path scoping needs to become more expressive later, consider
  adding explicit glob-based `supported_paths` / `ignored_paths` support
  instead of only prefix matching, so repositories can scope review by file
  patterns such as `*.py` or `src/**/*.py` when that proves useful
- capture human feedback and convert incorrect or noisy review comments into
  targeted regression tests
- make remediation decisions more legible so operators can see clearly why an
  issue was eligible, blocked, skipped, awaiting review, or excluded by policy
- tighten remediation and dashboard status language so operator-facing states
  distinguish not attempted, blocked by review, blocked by policy, validation
  failure, and completed outcomes more cleanly
- add remediation observability similar in spirit to staged-review
  diagnostics, including simple phase counts and bounded internal records for
  selection, skip reasons, fix generation, validation rejection, and publish
  outcomes
- revisit repo-defined remediation `validation_commands` as a hardening item
  rather than a currently solid supported feature; first define bootstrap
  ownership, tool availability expectations, and whether mutating normalization
  commands should remain part of the same surface
- add bounded remediation confidence with short operator-facing reasons so
  automation can communicate how strongly it stands behind a proposed fix,
  validation result, or blocked-remediation outcome without collapsing into a
  vague single-number score
- harden "why no remediation happened" messaging so no-op remediation runs
  still explain whether nothing was eligible, policy blocked execution, an
  active MR prevented action, or review state made remediation unsafe
- when the bot opens a remediation merge request, support automatically
  assigning a human reviewer so ownership is clearer and the handoff from
  automation to human review is more explicit
- detect when an open remediation merge request already exists for the same
  underlying issue and reuse, update, or explicitly supersede it instead of
  silently creating a duplicate path
- add a retry, rebase, or recreate option for remediation merge requests that
  become stale or unmergeable after repository state changes
- make remediation-generated functions follow repository conventions for type
  hints and docstrings more reliably, preferably through clearer prompt
  guidance and later repo-aware validation or config support
- add a clearer retry-explanation surface for operators so blocked, failed,
  and retry-eligible dashboard items explain their current state as directly as
  policy commands explain policy changes; prefer explanation-first before
  adding reset/requeue actions
- restructure the workflow dashboard so automation-ready items and
  human-follow-up items do not share one ambiguous `Needs Attention` bucket;
  likely split later into clearer sections such as `Queue Auto-fix`,
  `Needs Review` / `Review / Investigate`, `In Flight`, and `Completed`
- investigate monorepo dashboard scaling, including whether one dashboard per
  scoped repo area or domain would work better than one repo-global issue once
  item volume and ownership boundaries become too noisy for a single board
- make failed-item operator flows more explicit after diagnosis, so
  `Investigate Failure` does not stop at "understand the problem" but also
  leads more clearly toward the next appropriate action such as retry,
  environment/config fix, blocked state, or manual follow-up
- audit the operator policy surface so dashboard commands map more explicitly
  to actual remediation behavior around thresholds, exclusions, retry
  blocking, and review-gated automation
- replace repeated broad boundary `except Exception` blocks with a small
  shared wrap-and-log pattern at true provider or orchestration boundaries,
  preserving known domain errors and converting only unknown failures into
  typed repo-specific exceptions more consistently
- if developer-facing review tone still feels too cold in practice, consider a
  warmer greeting such as `Hi <MR author>,` with `Hi,` as fallback, but keep
  that as a UX refinement rather than an active defect track

Recommended guardrails for developer disagreement feedback:

- treat disagreement as bounded operator feedback, not as automatic global
  truth

Recommended cleanup pass after dashboard/remediation hardening:

- if repo-defined validation commands are kept after hardening, move
  `validation_commands` under the remediation config surface once the feature
  contract is explicit and reliable
- remove remaining flat config compatibility once migration-era support is no
  longer needed
- retire older severity-key aliasing once `bootstrap_severities` is the only
  intended config name
- harden `DashboardRemediationUpdater` retry boundaries so parser or integrity
  failures are not retried and flattened the same way as transient dashboard
  write races
- reduce remaining Sonar-shaped execution adapters and assumptions where the
  remediation core still carries older source-specific structure
- clean up older `ai-sonar-bot` naming in non-compatibility-sensitive places
  such as tests, labels, and defaults where that no longer reflects the
  product
- move GitLab-specific merge-request services out of `services/shared` once
  provider-neutral publish/review abstractions are real, so the shared package
  reflects actual cross-provider boundaries

## Post-V1 Architecture Cleanup

Goal:

- improve maintainability by grouping mature service areas into clearer domain
  packages once v1 behavior is stable

Recommended first step:

- group the current dashboard-related services into their own domain package,
  since dashboard, remediation workflow views, and reconciliation already form
  a clear architectural cluster

Why later:

- this is a maintainability improvement, not a current product-risk item
- the active priority remains live testing, trust, and operator workflow
  validation
- a domain reorganization will be easier once the workflow surface is more
  settled

Possible later follow-up:

- re-evaluate whether review and remediation should adopt the same domain
  grouping style after a dashboard-first cleanup proves useful

- for dashboard presentation, prefer producer-supplied compact human summaries
  or work-type labels over growing renderer-side text-pattern heuristics; keep
  renderer humanization as a minimal fallback, not the primary source of truth

- add a post-v1 `docs/review_bot/` documentation home with one overview or
  index doc so review-bot design, implementation, and testing docs stay
  separate but are easier to navigate from one entry point

- explore a separate GitLab-managed memory board or summary issue for slower-
  moving cross-workflow intelligence such as recurring review themes, repeated
  remediation patterns, fix outcomes, and operator feedback; keep structured
  JSON as the bot-facing source of truth and markdown as the operator-facing
  summary surface rather than introducing a database too early
- first use it only to affect later review passes on the same merge request
- later, use repeated disagreement patterns as prompt, ranking, or policy
  improvement input only after explicit review

### Dashboard Visibility For Review

Later, the dashboard can be improved to make review activity easier to scan
without replacing merge request notes as the primary review surface.

Potential improvements:

- make review status items easier to scan than the current generic review
  section rendering
- surface stable review outcome fields such as `findings_present`,
  `no_findings`, `manual_review_only`, reviewed SHA, and note URL more clearly
- keep merge request notes as the primary review surface while using the
  dashboard only for status, traceability, and quick scanning
- consider low-noise review summaries in dashboard metadata without copying the
  full MR note body
- revisit MR-to-dashboard linking if later workflow changes allow multiple
  dashboard items to share one merge request trace, since the current linkage
  intentionally assumes a simple one-remediation-item-to-one-MR model

### Failed Dashboard Items

Later, failed dashboard items should become a diagnosable operator queue rather
than a terminal sink.

Recommended direction:

- keep `failed` as "automation blocked" rather than "ignore forever"
- record clearer failure categories such as missing merge-request metadata,
  branch traceability mismatch, validation failure, and publish/auth failure
- make failed items easier to scan in the dashboard with reason, timestamp, and
  whether retry is sensible
- add bounded follow-up paths such as explicit retry, reopen-to-open for safe
  cases, or manual cleanup when traceability is broken
- keep turning repeated failed-item patterns into regression tests so the same
  reconciliation or remediation failure class happens less often over time

### Advisory Confidence Signals

Review confidence is already present in the review workflow, while
remediation-facing confidence remains a broader future platform capability.

Recommended shape:

- define remediation-facing confidence fields plus required reason text in the
  dashboard remediation workflow
- decide where confidence is recorded first for each workflow: dashboard item
  metadata, run summaries, review artifacts, or merge-request notes
- emit remediation confidence after bounded analysis/edit generation
- keep confidence advisory only: no auto-merge, no auto-close, no lifecycle
  transitions based on score alone
- add regression coverage for score presence, absence, and reason text
- document how operators should interpret low-confidence remediation or review
  outcomes

### CI/CD And Security Hardening

After the current hardening baseline, the platform can invest in broader
release and security follow-up work.

Potential follow-up work:

- harden GitHub release-to-GHCR publishing so tag and release mismatches are
  easier to detect and recover from
- keep dependency and container security guidance current alongside the
  existing `pip-audit` and `Bandit` baseline
- evaluate broader security scanning later around commonly used scanner
  platforms that could also feed the dashboard, rather than adding another
  one-off tool immediately
- add broader scanner or container/base-image coverage only after current CI
  noise stays acceptable

### Goal

Fetch one work item, analyze it, generate a code change with an LLM, validate
the change, and create a merge request for review.

Potential future work-item sources:

- SonarQube issues
- scheduled internal review dashboard items
- Jira tickets
- ClickUp tickets
- pipeline failures
- pull requests or merge requests

### Preconditions

This only works reliably if human-authored tickets follow a strict template,
similar to the structured nature of a SonarQube issue.

### Required Ticket Template Fields

- summary
- problem statement
- expected outcome
- target module or file hints
- constraints or out-of-scope notes
- acceptance criteria
- validation commands
- risk level

### Guardrails

- process one ticket per run
- reject vague or underspecified tickets
- reject tickets that imply broad refactors
- keep human review in the merge request
- prefer low-risk implementation tickets first

Pipeline failures should use similar guardrails, but the required context is
different:

- failed job name
- failing command
- stack trace or test failure output
- artifact or log links
- target service or package
- reproduction notes when available

Pull request review should be treated as a related but distinct workflow:

- input is an existing code change
- output is review comments, structured findings, or suggested patches
- the primary goal is analysis and review, not opening a new merge request
- when a dashboard exists, the review workflow should still publish the detailed
  result on the merge request first and only mirror review status to the
  dashboard

Scheduled internal review can also feed the fix workflow if it writes issues
into a strict dashboard template first:

- one scheduled review workflow scans the codebase
- it writes structured findings into a dashboard issue
- a later fix workflow consumes only dashboard items that match the required
  template exactly
- this keeps discovery and remediation separate, while still using the same
  shared engine underneath

Recommended dashboard item fields for this path:

- `id`
- `source`
- `type`
- `file`
- `line`
- `summary`
- `problem`
- `expected_change`
- `constraints`
- `acceptance_criteria`
- `validation_commands`
- `status`

Future note:

- keep `constraints` as a prompt-time execution input in v1
- revisit later whether non-empty constraints should also be surfaced in
  operator-facing outputs such as merge request descriptions, run summaries, or
  debug artifacts once real producer-authored examples exist
- revisit review finding ranking after live review-quality testing; if the
  current severity-only cap proves too coarse, rank capped findings using
  stronger evidence quality and, if added later, per-finding confidence rather
  than the review-level confidence signal

Why this is attractive:

- review and remediation stay decoupled
- humans can see and triage the backlog
- the fix bot only consumes structured, explicit work items
- the same model can later work for GitLab issues, GitHub issues, or another
  dashboard surface

### Architecture Direction

Introduce a provider-neutral work-item model and source interface:

- `WorkItemSource`
- `SonarQubeSource`
- `DashboardIssueSource`
- `JiraSource`
- `ClickUpSource`
- `PipelineFailureSource`
- `PullRequestSource`

Also split the current SonarQube flow into two explicit stages as the platform
expands:

- Sonar discovery and normalization
- generic remediation against one structured work item

That keeps SonarQube aligned with future dashboard-, pipeline-, and ticket-based
sources instead of treating Sonar as a special end-to-end path forever.

Also introduce separate workflow types on top of the shared platform:

- `FixWorkflow`
- `ReviewWorkflow`

Longer term, allow external or optional internal producer bots to plug into the
same contract by writing strict dashboard items that the remedy workflow can
consume. In that model:

- producer bots generate structured dashboard work items
- the dashboard acts as the shared control plane and queue
- the remedy bot consumes only supported dashboard item types
- new bot types can be added as producers without changing the remediation core

Potential shared internal model:

- `id`
- `title`
- `description`
- `type`
- `priority`
- `target_files`
- `acceptance_criteria`
- `validation_commands`

Shared engine responsibilities:

- selection and locking
- context building
- LLM orchestration
- patch application
- validation and retry
- branch and merge-request automation
- review reporting and comment publishing

Source-specific responsibilities:

- fetch and normalize source payloads
- determine eligibility rules
- provide source-specific context
- shape prompts where source semantics differ

Workflow-specific responsibilities:

- `FixWorkflow`
  - generate and apply a change
  - validate the change
  - create or update a merge request
- `ReviewWorkflow`
  - analyze an existing change
  - produce findings, summaries, and optional suggested edits
  - publish review output without creating a new branch by default

Future feedback-loop direction:

- when a remediation merge request is closed or otherwise rejected after review,
  let reconciliation attach bounded structured review findings back onto the
  reopened remediation item
- feed that structured review context into the next remediation attempt so the
  remedy bot can learn from the prior review pass instead of retrying blind
- keep this bounded and stateful by preserving attempt count, prior MR
  references, and retry limits rather than creating an open-ended loop

### Suggested Rollout

1. add a provider-neutral work-item model
2. extract a `WorkItemSource` interface from current SonarQube intake
3. add scheduled review dashboard generation with strict structured issue items
4. add dashboard issue intake through `DashboardIssueSource`
5. add pipeline-failure intake with structured job and log metadata
6. keep pull-request review as a distinct review workflow baseline while
   expanding intake sources
7. define the required Jira or ClickUp ticket template
8. implement Jira intake
9. validate that template quality is good enough for low-risk tickets
10. add ClickUp intake only after Jira, pipeline, and review flows are stable

## Deferred Beyond V1

- multi-issue processing per run
- automatic merge request approval or merge
- distributed or shared state storage
- support for GitHub in addition to GitLab
- advanced issue prioritization
- autonomous retry loops beyond one retry

## Minimal Onboarding

Future direction:

- take this on only after the current hardening and testing phase has produced
  stable workflows worth packaging more broadly
- provide a Renovate-style onboarding path where operators can enable the bot
  with one GitLab token, one OpenAI token, a small config file, and a drop-in
  CI setup
- minimize required per-repository customization by auto-discovering sensible
  defaults where possible

Suggested baseline experience:

- add GitLab and OpenAI tokens
- copy a small `.gitlab-ci.yml` integration from the example jobs
- optionally add `.zeroone-ops.json` for repo-specific tuning
- let the bot discover repository guidance such as `AGENT.md`, engineering
  standards, and technical design docs automatically

Possible follow-up capabilities:

- safer default review and dashboard schedules
- default-branch discovery
- automatic validation-command suggestions or common-project detection
- simplified push-auth setup for remediation workflows
- a clearer config reference that marks which JSON fields are required, which
  are optional, and what defaults apply, with a later path toward publishing a
  machine-readable schema for editor validation

## GitLab Dashboard (Shipped Baseline)

Status:

- GitLab dashboard foundation is already implemented
- dashboard parsing and rendering are in place with structured item support
- review status and Sonar discovery mirroring are already part of the shipped
  workflow

Future direction from this baseline:

- keep dashboard behavior deterministic and retention-bounded
- keep dashboard as operational state, not a permanent append-only ledger
- continue reducing CI dependence on local JSON state as concurrency grows

Purpose:

- make bot activity visible without relying on local JSON state
- show pending, in-progress, rejected, and completed SonarQube issues
- provide a lightweight operator control surface in GitLab

Suggested design:

- one persistent GitLab issue, for example `AI Code Ops Dashboard`
- markdown sections for:
  - open candidates
  - in progress
  - merge requests opened
  - rejected or manual-review items
  - recent failures
- each row tracks:
  - SonarQube issue key
  - rule
  - severity
  - file
  - current status
  - branch
  - merge request link
  - last attempt timestamp

Rules:

- use merge request and branch lookup as the hard dedupe mechanism
- use the dashboard issue as the visibility and operator layer
- keep local JSON state for local runs, but reduce CI reliance on it over time
- keep the dashboard design provider-portable so the same concept can map to a
  GitHub issue when GitHub support is added later
- treat the dashboard as operational state, not a permanent append-only ledger
- add retention rules so only active work and recent failures/reviews remain in
  the main dashboard
- move older completed or superseded items to an archive issue or later durable
  database-backed history

Longer term, replace JSON-backed runtime state with a database-backed state
store once concurrency and workflow count justify it.

Recommended direction:

- keep the current `StateStore` abstraction
- retain `JsonStateStore` for local and early-stage usage
- add a later `PostgresStateStore` or similar durable backend for:
  - run history
  - work-item dedup and locking
  - review revision state
  - dashboard item state
  - failure records and reporting

Future extension on top of that database-backed state:

- add a small operator UI where people can submit problems through a strict
  structured template instead of free-form tickets
- validate those submissions against supported work-item schemas before they
  enter the shared queue
- let the bots pick up those human-authored structured items through the same
  dashboard/work-item contract used by automated producers
- keep the UI focused on controlled intake and status visibility rather than a
  general-purpose ticketing system

Why later instead of now:

- JSON state is still simple and inspectable for the current scope
- a database adds schema, migration, hosting, and operational overhead
- the need becomes stronger once multiple repos, multiple workflows, and higher
  concurrency are active

Recommended retention direction:

- keep `open`, `in_progress`, and `mr_opened` items in the main dashboard
- keep only a recent window of review-status and failure entries
- prune older `done`, `ignored`, and `rejected` items from the main issue
- rely on merge requests, future archive issues, or a later database for
  long-term history
- implement dashboard cleanup through a separate maintenance service, such as a
  `DashboardMaintenanceService`, instead of spreading pruning and archival logic
  across discovery, review, and remediation updaters
- let that maintenance service own retention, stale-item reconciliation,
  archiving, and section cleanup so producer workflows stay simple

Done when:

- CI runs update the dashboard issue after each execution
- operators can see current bot state without inspecting pipeline logs
- dashboard content stays consistent with open merge requests and selected issues

## Post-V1: Symbol-Safe Rename Handling

After the base SonarQube remediation flow is stable, add symbol-aware reference
checks so naming issues can be handled safely instead of being excluded by the
v1 guardrail.

Purpose:

- support low-risk rename issues without breaking surrounding code
- replace the current message-based rename skip with explicit safety checks
- widen the auto-fixable issue set only when reference integrity can be verified

Suggested design:

- classify rename-style SonarQube rules explicitly instead of relying on message
  text alone
- scan the file for symbol references before accepting a rename proposal
- reject renames when the symbol has additional references outside the proposed
  edit scope
- prefer language-aware or AST-backed analysis when exact text search is not
  reliable enough

Rules:

- do not allow rename-style auto-fixes without a reference safety check
- keep the fallback conservative: ambiguous rename cases remain manual
- widen rename support one narrow rule class at a time

Done when:

- rename-style SonarQube issues can be auto-fixed only when reference safety is
  verified
- risky or ambiguous rename proposals are rejected deterministically
- the v1 message-based rename skip can be removed or reduced to a last-resort
  fallback

## Post-V1: Complex Single-File Refactors

After the narrow v1 rule set is stable, add controlled support for harder
single-file issues that are still local to one function or file, but are not
safe as simple exact replacements.

Examples:

- duplicated branch rules such as `python:S1871`
- branch-merging logic
- small control-flow simplifications
- local duplicated-condition refactors

Purpose:

- expand beyond exact replacement issues without jumping to multi-file changes
- support refactor-style SonarQube rules that need broader function context
- keep the automation scope explicit and graduated by rule family

Suggested design:

- introduce a separate post-v1 issue class for complex single-file refactors
- collect broader function-level context, not just the immediate snippet
- extend structured edits beyond exact replacement to richer local refactor
  operations
- keep bot-rendered diffs as the execution artifact
- require validation commands for this class instead of allowing unvalidated
  runs

Rules:

- do not include duplication or branch-merging rules in the v1 allowlist
- widen support one rule family at a time
- require stronger review and rollout evidence before promoting a rule into the
  supported set

Done when:

- the bot can safely handle one or more duplication or branch-merging rules in
  a controlled post-v1 scope
- those rules use stronger context and validation requirements than the v1
  exact-replacement path
- rule support is documented explicitly instead of inferred from severity alone

## Post-V1: GitHub Support

After the GitLab-first v1 is complete, GitHub support should be added as a
focused follow-up rather than folded into the v1 scope.

Required changes:

- add a GitHub provider client alongside the existing GitLab client
- introduce an SCM provider switch in configuration
- extract a provider-neutral publish interface for merge request or pull request creation
- rename GitLab-specific publish concepts in shared models and services to neutral change-request terms where needed
- support GitHub repository identification and token configuration
- implement duplicate pull request detection for GitHub
- map labels, reviewers, and assignees to GitHub APIs
- update state fields if they are too GitLab-specific, for example `mr_url`
- add GitHub integration tests and CI coverage for the publish layer

Done when:

- a validated branch can create a GitHub pull request through a provider-neutral publish flow
- the state model can persist either GitLab merge request URLs or GitHub pull request URLs cleanly
- shared workflow code does not depend on GitLab-only terminology outside the GitLab provider layer

## Post-V1: Service Layout Refactor

As the repository grows, the flat `services/` directory should eventually be
grouped by workflow or domain once the dashboard-backed remediation path is
stable.

Suggested direction:

- group workflow-specific code into folders such as `services/sonar/`,
  `services/review/`, and `services/dashboard/`
- keep only truly shared execution, publish, validation, and state helpers at
  the top level or in a small shared area
- align folder structure with the actual workflow boundaries rather than adding
  deep nesting everywhere

Why later instead of now:

- the workflow boundaries are still shifting while dashboard-backed remediation
  is being designed
- grouping too early can create churn before the final operating model settles
- the refactor will be more coherent once the producer/consumer split is fully
  implemented

Done when:

- workflow-specific services are easier to navigate and reason about
- shared services are clearly separated from source- or workflow-specific code
- the service layout matches the stable product architecture more closely

## Post-V1: Renovate-Style GitLab Token Handling

After the current CI configuration is stable, move GitLab push authentication
closer to the bot so `GITLAB_TOKEN` behaves more like a single coupled bot
credential.

Purpose:

- reduce CI-specific git remote rewriting
- let one GitLab token cover both API and push behavior
- make the bot behave more like Renovate in GitLab environments

Suggested design:

- keep `GitLabClient` responsible only for GitLab API calls
- move push-auth setup into the git layer, for example `BranchManager` or a
  dedicated git-auth service
- consider a bot-owned working clone inside the container, similar in spirit
  to Renovate, so the bot does not depend as heavily on CI-side
  `safe.directory`, git identity bootstrap, or host-checkout ownership quirks
- if explored, keep the design explicit about when the bot should operate on
  the mounted repository checkout versus an internal bot-managed clone, so
  local workflows and CI workflows do not silently diverge


## Post-V1: Dashboard Hardening

- group repeated review entries by merge request in the dashboard instead of treating each review pass as the primary row; show the latest review state plus compact continuity outcomes such as unresolved/new/resolved once overlap reconciliation is stable enough to trust
- make repeated merge-request review history easier to scan operationally, so
  one MR with multiple passes reads as one review lineage rather than several
  disconnected review rows
- investigate MLflow tracing as a future LLM/workflow observability layer for
  review and remediation stages, likely alongside broader OpenTelemetry-based
  application tracing rather than as a replacement for general runtime
  observability
- keep watching the GitLab prior-review author filter in CI: if `/api/v4/user` lookup is unavailable, the bot currently falls back to any MR note with a valid machine-safe block; revisit whether that should stay fail-open or move to a stricter trust boundary once live testing gives us enough signal
- harden overlap reconciliation later by moving from raw positional indices to stable packet-local finding ids (for example `current-0` / `prior-0`) so the overlap prompt contract is less fragile than machine index references

## Post-V1: Review Pipeline Hardening

Status:

- the staged review pipeline was implemented from this plan
- the live path now runs:
  - candidate generation
  - grounding
  - precision / reconciliation
  - overlap continuity classification
  - artifact builder
  - validator gate
- legacy single-flow adapters were removed after the staged path became the
  only production path

What remains later:

- build a small labeled evaluator set from real review outcomes so prompt
  changes, schema changes, and validator/reconciliation rules can be compared
  against concrete false-positive, contradiction, suppressed-concern, and
  context-miss examples
- watch whether same-SHA reruns are materially more stable under the staged
  flow, and tighten prompts or validator rules if live drift remains too high
- consider persisting a bounded form of previously dropped candidate provenance
  for repeated-run stability and evaluation, since current cross-run memory is
  anchored only on previously accepted findings
- strengthen same-SHA precision behavior so previously accepted findings act as
  a stronger stability anchor and reruns do not easily switch to a different
  accepted concern on the exact same reviewed commit
- tighten clean-pass explanation wording so published `no_findings` reviews
  explain review truth in developer-facing terms rather than leaking staged
  pipeline mechanics such as empty candidate sets or bounded precision rules
- tighten published finding wording so it makes the narrowest supported claim,
  for example distinguishing response-body truth from HTTP response semantics
  when the visible code only proves one of those layers
- harden continuity/overlap matching when a prior concern survives into the
  next pass, so retained findings are not incorrectly counted as newly
  introduced concerns
- remove any remaining open-MR polling assumptions from the review path and
  keep review intake intentionally CI-triggered per merge request, so same-SHA
  reuse and review selection do not have to support a dormant project-wide
  polling mode
- add an internal observability-report workflow that pulls staged-review
  diagnostics, correlates same-SHA reruns and dashboard/feedback-log context,
  and generates a visualized hardening report for review quality analysis
- revisit bounded repair only after testing produces concrete recurring
  contradiction classes that are safe to repair without changing reconciled
  review meaning
- keep reviewing whether overlap continuity should remain a separate narrow LLM
  stage or eventually fold into precision after enough live evidence exists

## Post-V1: Decision Registry

Create a small structured decision registry so current architectural and
workflow truth is easier for humans and coding agents to query than the full
design-library markdown corpus.

Suggested direction:

- store active decision records in `docs/decisions/`
- keep one machine-readable file per important decision instead of one large
  shared hand-edited registry file
- link each decision to:
  - affected workflow areas
  - implementing files
  - supporting design docs
  - superseded earlier decisions where relevant
- generate a combined markdown index and machine-readable graph/index later
- use a separate decision-tool package or package-like module rather than
  adding this into the `zeroone-ops` runtime runner flow
- provide a small interactive CLI such as:
  - `repo-decisions new`
  - `repo-decisions validate`
  - `repo-decisions build-index`
- use the registry to make intentional workflow boundaries and invariants
  easier for review or coding agents to retrieve without searching the full
  design corpus first

Why later:

- the current codebase now has enough design history that a normalized decision
  layer would help, but the immediate focus remains workflow hardening and live
  feedback
- a small manual seed set is more realistic than trying to infer all decisions
  automatically from existing markdown
- a distributed source plus derived index model is simpler to maintain than a
  fully automatic ontology pass or a single conflict-prone shared registry

Done when:

- the highest-value workflow and safety decisions have stable ids and active
  status
- agents can answer "what is the current rule and where is it implemented?"
  without searching the full design library first
- contributors can add a new decision through a simple scaffolding CLI instead
  of hand-writing registry files from scratch
