## ZeroOne Ops Operator Runbook

Issue-mode finding sync excludes open and indexed closed dismissed findings before
allocating capacity. The aggregate backlog reason `dismissed` explains suppression;
these findings do not count as promoted or unchanged work. Dry runs use the same
inventory without writes.

This runbook describes how to operate the current ZeroOne Ops workflows in
GitLab CI and GitHub Actions. Provider-specific setup details call out the
relevant platform where their control planes differ.

V1 supports GitHub and GitLab issue mode only. Legacy dashboard runtime and
commands are removed. Existing installations must follow the
[v1 migration guide](migration-v1.md), including backup and explicit cleanup of
meaningful local dashboard history. Remote dashboard issues are not modified.

The supported GitHub/GitLab installation templates pin `1.0.0`; update any
`ZERO_ONE_OPS_VERSION` override when upgrading. Use that stable pin after image
publication, or the exact RC tag during testing. Latest-RC validation on both
providers was confirmed by the operator on 2026-10-29 and is recorded in the
[release-readiness checklist](roadmap.md#v1-release-readiness). Each installation
still needs its own cutover checks, policy verification, and current scanner
reports before automation resumes.

Naming note:

- product brand: `ZeroOne Ops`
- technical release and image slug: `zeroone-ops`
- operator-facing commands, config examples, and container paths now use the `zeroone-ops` names

The old dashboard command aliases no longer exist. Use `zeroone-ops policy run`
for policy processing and the neutral findings, remediation, and work-items commands.

## Offline Workflow Verification

From a development checkout with dependencies installed, run
`just test-scenarios`. The existing Quality pipeline includes these scenarios
through normal pytest collection; there is no new operator CLI command or CI job.
Both provider paths cover batch creation through real intake, execution, pytest
validation, and local Git push, including successful and exhausted correction.
Review scenarios exercise real candidate/precision prompts, finding lineage,
artifact publication, verified work-item projection, and isolation between
requests using actual local base/head commits. Repeated reviews of one request
exercise latest-comment loading, unresolved/resolved/new overlap decisions, and
inline-comment reuse across successive commits.
The suite requires Git and installed development dependencies, but no credentials,
container runtime, model calls, scanner installation, or remote provider access.

Scripted model and in-memory HTTP responses make workflow outcomes reproducible;
they do not establish model precision or live API compatibility. Continue using
the GitLab test app for authorized real-model/live-provider RC checks. Same-SHA
reuse, projection-repair chains, operator requeue, and lifecycle remain outside
this initial scenario suite. Review SDK responses are typed scripts: prompt
construction and schema selection run, but SDK response parsing is not tested.
See the [scenario guide](https://github.com/JustinMelger/ZeroOne-ops/blob/main/tests/zeroone_ops/integration/scenarios/README.md)
for isolation and coverage boundaries.

## Documentation Website

The operator site is published at
[justinmelger.github.io/ZeroOne-ops](https://justinmelger.github.io/ZeroOne-ops/).
It follows `main`, not a particular release. For release-specific instructions
and templates, browse the matching
[Git tag](https://github.com/JustinMelger/ZeroOne-ops/tags).
The runbook remains the canonical procedural reference; entry pages link to its
sections without duplicating detailed procedures.

### Contributing Documentation

Use Python 3.13 and uv. Documentation dependencies live in the `docs` group,
which is also included by `dev` so a normal `uv sync --locked` can run the full
test suite. They are not application runtime dependencies. For docs-only work:

```bash
uv sync --locked --only-group docs
just docs-serve
just docs-build
```

The preview server is local. Stop it before running a separate clean build.
`just docs-build` performs a clean, strict Zensical build: broken local links
and missing anchors fail the build. Output goes to ignored `site/`; builder
cache goes to ignored `.cache/`. A docs-only sync replaces the current virtual
environment's packages; use `uv sync --locked --all-groups` before returning to
application development.

Maintain the explicit, root-anchored public-page allowlist and navigation in
[`zensical.toml`](https://github.com/JustinMelger/ZeroOne-ops/blob/main/zensical.toml)
when adding a page. Design history, `docs/internal/`, and the repository-only
index are excluded from both output and search. Use local Markdown links for
published pages and GitHub links for source, templates, tests, or excluded designs.
Do not add credentials, live trace exports, or private operational notes to public pages.

### GitHub Pages Setup

A repository administrator must select **Settings > Pages > Build and deployment
> Source: GitHub Actions**, then restrict the `github-pages` environment's
deployment branches to `main`. No personal access token or application secret
is needed for documentation publishing.

The Documentation workflow builds pull requests without deployment privileges.
Successful `main` pushes and manual runs on `main` upload only `site/` and deploy
through the official Pages artifact actions. Other branches cannot deploy.
No generated HTML or `gh-pages` branch is committed. Do not enable
`pull_request_target` or add model/provider credentials to this workflow.

Automated build acceptance and live publishing acceptance are separate. After
merging, verify the deployment URL, mobile navigation, search, code blocks, and
the review diagram; record that acceptance in the roadmap. Local builds do not
confirm repository Pages settings or a successful live deployment.

## Purpose

Use this document when you need to:

- configure the bot in a target repository
- understand what a normal run should do
- diagnose skipped runs, failed runs, or merge request reuse
- know which credentials and permissions are required
- run the merge request review workflow and validate its output

## Operating The Control Plane

The installed CI workflow owns ZeroOne Ops CLI commands. Operators normally
work through provider-native records:

| Operator need | GitLab | GitHub |
|---|---|---|
| Change automation policy | Comment on the policy issue | Comment on the policy issue |
| Recover a blocked item | Comment on the work-item issue, then run the control-plane job | Comment on the work-item issue; the recovery workflow runs on that comment |
| Inspect an active remediation | Work-item issue and merge-request link | Work-item issue and operational-summary link |

Both provider templates compose the same jobs: finding sync, remediation,
lifecycle reconciliation, policy processing, and recovery processing. Normal
operation is scheduled; manual runs are for rollout and operator follow-up.

## Supported V1 Scope

The current v1 automation scope is intentionally narrow:

- staged review for one GitLab merge request or GitHub pull request per run
- normalized SonarQube and configured SARIF findings
- one eligible remediation work item per run
- low-risk single-file fixes only
- structured-edit generation with bot-rendered diffs
- structured edits must touch exactly one file
- issue-mode remediation branches, commits, and change requests use `fix` only
  for analysis-declared behavioral corrections; typing, lint, test, and
  maintenance changes use `chore`
- provider-native GitLab merge request or GitHub pull request creation in
  `ci` mode
- policy-controlled promotion, lifecycle reconciliation, and explicit operator
  recovery for blocked remediation
- bounded GitHub review inline comments when enabled in the repository config

V1 does not include multi-file remediation, autonomous test repair, automatic
recovery of blocked work, or a database-backed control plane.

Current config shape for rollout:

- shared runtime settings remain top-level
- review behavior lives under `review`
- remediation policy lives under `remediation`
- provider-specific metadata lives under `gitlab` or `github`
- finding sources live under `sonarqube` and `sarif` when configured

In practice, the main remediation rollout keys now are:

- `remediation.bootstrap_severities`
- `remediation.max_retry_count`
- `remediation.max_active_work_items`
- `remediation.source_priorities`
- `remediation.validation_feedback_enabled`
- `remediation.validation_setup_commands`
- `remediation.validation_commands`
- `remediation.analysis.max_file_bytes`
- `sonarqube.mock_issues_path`
- `sarif.artifacts`
- `sarif.artifacts[].severity_mapping`

Authority note:

- `remediation.bootstrap_severities` is the bootstrap/default seed for a new
  control-plane severity policy
- once canonical policy state exists, remediation pickup follows that policy
  instead of treating config severity as the active operator control plane
- if neither config severity nor control-plane severity policy exists yet, the
  bootstrap default is `low` and `medium` enabled with `high` disabled
- GitLab operators change ongoing policy through strict `/zeroone policy ...`
  comments on the dedicated policy issue; GitHub repository admins do the same

Validation feedback is opt-in through `remediation.validation_feedback_enabled`.
When enabled, remediation captures validation evidence before applying a
single-file patch. It may retry once for a normal failure from a previously
passing command, or a new structured diagnostic. Callers in a traceback do not
expand edit permissions. Known baseline failures are not sent as repair requests.

The default is `false`. For a repository with existing MyPy debt, explicitly
opt in and use stable plain-text output, for example:

```json
{
  "remediation": {
    "validation_feedback_enabled": true,
    "validation_setup_commands": ["uv sync --all-groups --locked"],
    "validation_commands": [
      "uv run ruff format --check .",
      "uv run pytest",
      "uv run mypy src --no-error-summary --no-pretty --no-color-output"
    ]
  }
}
```

MyPy and Ruff check diagnostics are compared by occurrence, including code and
message. Verified unchanged source lines may move after an import removal;
ambiguous relocation stays conservative. Recognized tool summaries may change
as errors are removed. Unsupported diagnostic contracts (including pytest and
formatting) must pass at baseline and before publication; repeated failed output
is not accepted. This is stricter than the previous exact-output fallback.
Generic exit 1 with evidence may receive correction; pytest collection-error
exit 2 requires exception evidence. Usage errors, no tests collected, and unknown
nonzero exits block. Missing tools, timeouts,
permission errors, scanner execution errors, unexpected output, and incomplete
command results block without model regeneration. A mixture of operational and
normal failures also withholds correction. Repair tooling before retrying.
Logs report baseline mode and comparison reasons without raw diagnostic output.
`baseline_failure_count` counts failed commands, not findings.

A supported tool's normal failure after a clean baseline may receive one
correction even when its output format is not recognized, such as Ruff's
default syntax-error display. That fallback never preserves a failing baseline
or authorizes publication. Contradictory evidence and unresolved paths still block.

On failure, **Last Execution** and CLI output identify the command, exit code,
baseline/post-edit phase, baseline exit, and whether correction was disabled,
withheld, or exhausted. A sanitized diagnostic excerpt keeps the exception
and relevant traceback locations instead of only the first session-header
characters. It is limited to twenty lines and 2,000 characters.
Pytest-prefixed syntax-error locations identify the failing file and line, while
the corresponding source displays remain excluded. Omission
notices and the workflow-log link indicate where evidence is incomplete.
Recognizable credentials are redacted, but avoid secrets in validation command
arguments or output; redaction cannot identify every possible secret.

`0 items / 2 errors` means collection failed while loading test modules, not
that test discovery was disabled. A previously passing pytest command can
receive one correction for a collection exception even when importing tests
appear in the traceback. The original file remains the only editable scope.
Validate this scenario on GitHub and GitLab after deploying, separately from
automated acceptance; do not infer that the failed edit was present on `main`.

After deploying, live-test an unused-import removal against existing MyPy
errors and an incorrect annotation that introduces an error. Neither automated
tests nor publication prove that every targeted scanner finding was resolved;
keep live GitHub/GitLab acceptance separate. No remote demo config is changed
automatically.

V1 rejects retired configuration aliases, even when their canonical replacements
are also supplied. Use top-level `platform`, `remediation.target_branch`,
`remediation.bootstrap_severities`, and remediation-owned validation commands.
The [migration guide](migration-v1.md) lists the removed keys and replacements.
Deprecated but functional context/helper tuning settings still emit warnings.

The bot currently excludes rename-style issues by design. Rename changes need
symbol-reference safety checks that are not part of v1 yet.

If the LLM proposes a structured edit that touches more than one file, the run
fails at analysis instead of trying to widen scope automatically.

The review workflow is provider-native:

- one merge request or pull request per run
- one deterministic summary note per reviewed revision
- dedup by change-request identity and head SHA
- bounded GitHub inline comments when enabled in `review.inline_comments_enabled`
- no code modification in the review workflow
- draft change requests skipped by default

Review correctness claims must identify what the diff introduces or newly
invalidates, the visible requirement it violates, and the supported consequence.
Changed annotations do not make existing runtime defects new, but can introduce
invalid contracts or import-time failures themselves. API-impact claims respect
visible request validation; narrower helper concerns need a code-backed contract.
Missing callers alone do not require manual review, and direct deterministic
defects remain reportable without proving branch-wide reachability. These are
model instructions, not a guarantee of review precision or a suppression filter.
Both candidate generation and precision receive the same bounded remediation
evidence. Batch attempt members are supplied only through verified work-item
linkage and remain untrusted context, not proof that the findings were resolved.

The control plane includes scheduled lifecycle reconciliation:

- GitLab and GitHub work-item issues retain change-request
  traceability
- deterministic transitions for merged, closed-unmerged, stale, and blocked
  remediation work
- CI-only live execution, with local inspection limited to `--dry-run`

Policy processing is separate from finding sync and remediation:

- GitLab replays authorized notes from the dedicated policy issue into canonical policy state
- GitHub replays comments from the dedicated policy issue
- malformed or unauthorized commands are visible in logs and do not mutate
  authoritative state

Blocked remediation recovery is separate as well. Authorized GitLab Maintainers
and Owners or GitHub repository admins comment `/zeroone remediation requeue` or
`/zeroone remediation dismiss` on the affected work-item issue. Recovery only
queues state. The normal remediation job remains the sole owner of patch
generation, validation, branch creation, and change-request publication.

For a conflicted remediation PR/MR, v1 supports manual recovery:

1. Close the PR/MR without merging; deleting its branch alone is not enough.
2. Run or wait for `zeroone-ops work-items sync-status` to mark the linked
   work item `blocked`.
3. Post a new `/zeroone remediation requeue` comment on the work-item issue.
4. If current policy permits, recovery queues a fresh attempt; the next
   remediation run creates a new branch and PR/MR. Recovery history retains
   the previous request link.

An open but conflicted request is not automatically blocked. Conflict detection
and automated branch repair are not part of v1.

When the review of an open remediation pull or merge request reports actionable
findings, its authoritative work-item issue moves to
`review_feedback_required`. The issue renders bounded review evidence and the
same `/zeroone remediation requeue` command. That command queues one revision
of the existing branch only after ZeroOne Ops verifies the reviewed head is
still current; it never creates a second pull or merge request. Commands on
the pull or merge request itself are not authoritative.

Actionable review comments link back to the uniquely linked work-item issue
with requeue instructions. Revision execution reads source and guidance only
after checking out the reviewed branch. Preparation, context, validation, or
publication failures return the item to `review_feedback_required`, preserving
its request link and feedback and recording the failure in `Last Execution`.
When failure evidence matches the latest revision command and reviewed SHA,
the issue also displays **Last revision failed** above the requeue guidance.
This display-only notice disappears when another revision is queued or succeeds.
A revision dry run checks eligibility without checkout or model analysis.
Live revision checkout and push reject refspec syntax and invalid Git branch
names before remote access; provider branch metadata is not treated as Git
instructions.

Each accepted revision command is consumed once, including when execution
fails. Send a new command after inspecting the failure; rerunning a polling job
or redelivering the original comment does not authorize another attempt.
The command must also be newer than the current feedback-action boundary.
Comments posted before the review or during an attempt cannot authorize a
later revision or retry its failure. Historical feedback without this boundary
requires a review-projection refresh followed by a new requeue comment.
Claimed revisions cannot be selected again before stale-claim recovery. A new
clean review cancels queued revision work; a manual-only review preserves any
prior actionable feedback and requires a fresh operator decision.

If a revision push fails in a reused workspace, its local commit may remain
ahead of the reviewed remote branch. Use a fresh checkout for the next
authorized attempt; v1 does not reset or discard existing local commits. If
the remote head changed, obtain a current review before requeueing.

Same-SHA projection repair reuses persisted structured review evidence. Older
records without that evidence remain pending with a warning requiring a new
review, rather than silently losing the findings.

When bot analysis dismisses a work item as unsuitable for automatic remediation,
the work item stays terminal and records the decision in `Last Execution` with
its run reference. Dismissed work is not offered a requeue command.

The provider-native control plane renders an operator policy surface:

- current severity policy and excluded issue classes are shown for visibility
- GitLab and GitHub operational summaries are derived views, not authoritative
  mutation surfaces

## Required CI Variables

Define these variables in the target GitLab project or group:

- `GITLAB_URL` and `GITLAB_TOKEN` for issue, policy, recovery, lifecycle, and MR operations.
- `OPENAI_API_KEY` and optionally `OPENAI_MODEL` for remediation and review.
- `SONARQUBE_URL`, `SONARQUBE_TOKEN`, and `SONARQUBE_PROJECT_KEY` only when SonarQube intake is enabled.
- Scanner-specific credentials only in the producer jobs that require them.

Optional variables:

- `GITLAB_PROJECT_ID`
  - not required in GitLab CI when `CI_PROJECT_ID` is present
- `ZEROONE_OPS_EXECUTION_MODE`
  - should be `ci` for pipeline usage
- `ZEROONE_OPS_OPENAI_SOLUTION_OUTPUT_PATH`
  - only needed if you want a non-default local artifact path
- `ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI`
  - defaults to `false`
  - set to `true` only for debugging

## Execution Trust Model

Validation and setup commands execute arbitrary programs. Treat
`remediation.validation_setup_commands` and
`remediation.validation_commands`, plus repository code that those commands
invoke, as executable CI policy rather than ordinary configuration. Review
changes to these fields with the same care as CI workflow changes.

Privileged remediation jobs must load the ZeroOne Ops configuration from a
protected default-branch revision and run only from trusted triggers, such as
scheduled or manually dispatched workflows. Do not execute remediation setup or
validation commands in pull-request review jobs.

Trusted configuration is necessary but not sufficient: commands such as
`npm test`, `make test`, and `uv run pytest` can run repository scripts, build
hooks, and test code. Use least-privilege credentials, do not expose unrelated
secrets, and assume commands can access the workspace, network, and environment
provided to the job. Apply the same model to GitHub Actions and GitLab CI.

### Runtime Workspace Outputs

Remediation permits untracked generated outputs only when their exact
repository-relative paths are configured as `state.path`, a
`sarif.artifacts[].path`, or `openai_solution_output_path`. This avoids a
repository `.gitignore` requirement for ZeroOne-owned runtime files.

The exception does not cover directories, globs, unconfigured artifact files,
or any tracked, staged, deleted, renamed, copied, or conflicted path. Keep
operator changes outside these exact outputs clean before running remediation.

## Required Token Permissions

`SONARQUBE_TOKEN` must be able to read open issues for the configured project.

`GITLAB_TOKEN` must be able to:

- push branches to the target repository
- create merge requests
- read open merge requests for duplicate detection
- read and update the policy issue, authoritative work-item issues, and derived summary

In practice, this means the token should have:

- API access for merge request operations
- repository write access for branch pushes

Store CI secrets such as `GITLAB_TOKEN`, `SONARQUBE_TOKEN`, and
`OPENAI_API_KEY` as masked and protected variables. When CI rewrites the git
remote for authenticated pushes, avoid enabling shell tracing around that step.

`OPENAI_API_KEY` must be valid for the configured `OPENAI_MODEL`.

For GitHub-hosted release workflows:

- `RELEASE_PLEASE_TOKEN` must be available to the release workflow when using
  release-please automation
- prefer repository or organization secrets rather than hard-coded workflow
  values

Dependency maintenance uses the hosted Renovate GitHub App and `renovate.json`,
not a scheduled GitHub Actions workflow. Enable the app for this repository;
`RENOVATE_TOKEN` is no longer required here. Normal updates run during Monday's
06:00-12:00 Europe/Amsterdam window, with at most two open PRs and one new PR
per hour. Python, GitHub Actions, and container non-major updates are grouped
separately with a seven-day release-age delay. The PyPI cooldown applies to all
normal update types, including majors, matching `tool.uv.exclude-newer`.
Major approval does not bypass that cooldown: pending versions are filtered
before selection. Major upgrades also require approval in the Dependency
Dashboard; automerge is disabled. Vulnerability-alert PRs
retain Renovate's default schedule/rate-limit exemptions. Existing ordinary
branches also wait for the maintenance window before updates.

After correcting a cooldown rule, merge it into the default branch before
asking Renovate to rebase or recreate an affected dependency PR. A manifest
requiring a version younger than the uv cutoff cannot resolve to an older
version; keep the constraint and lockfile consistent rather than disabling the
cutoff. An urgent security fix may need a separately reviewed temporary uv
exception because Renovate's security exemptions do not disable uv's policy.

For pull request review, `GITLAB_TOKEN` must also be able to:

- list open merge requests
- read merge request changes
- create merge request notes

## Release Checklist

Use this lightweight checklist before cutting a stable release tag.

1. confirm the working tree is ready and the intended version/tag is clear
2. confirm CI quality checks are green:
   - `uv run ruff check .`
   - `just architecture`
   - `uv run mypy src`
   - `uv run bandit -q -r src`
   - `uv run pytest`
3. confirm required release and runtime secrets are configured:
   - `RELEASE_PLEASE_TOKEN` for GitHub release automation if used
   - `OPENAI_API_KEY` where live review or remediation flows will run
   - `GITLAB_TOKEN` for GitLab-backed live workflows
4. when using release-please, prefer squash merge with a conventional PR title
   so the commit that lands on `main` stays parseable for release automation
5. if the change is significant, publish and test a prerelease tag first, for
   example `zeroone-ops-vX.Y.Z-rc.N`
6. confirm the publish-image workflow smoke test passes for the container:
   - `--help`
   - `review --help`
   - `policy --help`
7. confirm README, runbook, and example CI docs still match the current release
   and image naming
8. record any known rollout caveats before cutting the stable tag

A stable release is ready when the checklist is complete and there are no known
blocking rollout issues.

## Expected Pipeline Behavior

### Finding Dogfood

The repository's Finding Dogfood workflow checks out the default branch and only
runs there. Daily and ordinary manual runs scan `src/` with MyPy, Ruff using the
repository configuration, and the existing pinned Semgrep `--config auto` scan.
No findings is a healthy result; this workflow does not deliberately generate
maintenance work when CI is already clean.

For feature testing, manually enable `include_test_findings`. The workflow also
scans `tests/` and publishes `artifacts/mypy-tests.sarif` as `mypy-tests-sarif`,
mapped to medium priority. A temporary configuration in `RUNNER_TEMP` copies the
root configuration and adds only this artifact. Ordinary runs use the root
configuration unchanged. Test findings create real issues, share the configured
five active-work slots, and can be selected by scheduled remediation. The new
source uses the default priority tier of 100. Subsequent daily runs do not collect
that source, so they do not resolve its work merely because the source is omitted.

The first source-only scan changes the old `mypy-sarif` inventory: eligible
unlinked test findings previously published under that ID may close as
`no_longer_detected`. Linked, in-progress, blocked, and dismissed work remains
protected. The optional test source does not migrate or reuse those old identities.

MyPy and Ruff exit codes 0 and 1 are accepted; other scanner failures, failed MyPy
conversion, or missing/empty SARIF files stop the workflow before finding sync.
Semgrep must exit successfully. Scanner exit status is logged immediately and
available SARIF/MyPy JSON artifacts are uploaded even on failure. This workflow
skips the entire sync after a producer failure; application-level partial-source
handling remains unchanged.

For rollout, first run the default source-only workflow and inspect the source
counts, reconciliation results, and summary. Only then enable a manual test run
if real test-related work items are wanted. Explicit/custom Semgrep rule curation
remains a separate follow-up.

### Normal Operations
Finding sync excludes indexed dismissed work before allocating promotion capacity.
Before creating a new issue, it rechecks closed dismissals when the planning
inventory had no match. A dismissal detected at this point suppresses creation and
is reported as dismissed backlog; the next sync can fill the unused slot. This
read-before-create safeguard is not an atomic provider reservation.

SonarQube intake reads the complete paginated inventory before applying policy,
source priorities, and promotion capacity. Page size is a transport setting, not
a finding limit. If collection fails (including a server pagination limit),
CI logs a bounded warning and discards that source's partial results. Other
available sources still sync. Existing SonarQube work stays unchanged and active
items still consume capacity; absence is never inferred from a failed scan.
Check SonarQube availability or query limits and rerun finding sync.

Pagination is not an atomic scanner snapshot. A scan changing during collection
may require a later rerun; inconsistent page metadata or duplicate keys cause the
source to be marked unavailable rather than interpreted as complete.

In normal `ci` mode, one run should do the following:

1. collect configured finding sources, such as SonarQube and SARIF artifacts
2. normalize findings and sync them into the provider-native issue control
   plane under current policy and capacity
3. process authorized policy and recovery commands
4. select one eligible approved work item for remediation
5. build focused context, run OpenAI analysis, and request one structured edit
6. apply and validate the bounded patch
7. commit and push a branch, then create or reuse a GitLab merge request or
   GitHub pull request
8. reconcile linked change requests later through `work-items sync-status`

If no eligible issue remains, the run should exit cleanly with `no_issue`.

## Expected Review Workflow Behavior

In normal `ci` mode, one review run should do the following:

1. if `CI_MERGE_REQUEST_IID` is present, fetch only that merge request
2. otherwise, fetch open GitLab merge requests
3. skip merge request revisions already reviewed for the current head SHA
4. select the triggering merge request or the next reviewable merge request
4. load changed-file diff data and bounded local source context
5. run OpenAI review analysis
6. classify the result as:
   - `findings_present`
   - `no_findings`
   - `manual_review_only`
7. publish one deterministic summary note unless the run is a dry-run
8. persist the reviewed MR IID and head SHA in state

If no reviewable merge request remains, the run should exit cleanly with `no_issue`.

## Expected Merge Request Shape

The merge request should contain:

- one issue per branch
- labels from `examples/.zeroone-ops.json` or the repository-specific runtime
  config derived from it
- a deterministic description template with:
  - an operator-facing summary of the concrete edit and why it is needed or safe
  - issue key
  - rule
  - severity
  - type
  - file
  - line
  - issue message
  - validation outcome and executed commands, independently of feedback mode

The `Validation` section distinguishes `Validation passed`, `Validation baseline
preserved`, and `No validation commands configured`. Missing retained evidence
is shown as `Validation evidence unavailable`, including publication-only
retries that lack the original result. Publication success alone never implies
validation passed. No raw command output is included. Same-request revisions
do not currently refresh this section; check the revision's workflow logs for
its validation result.

## Recommended GitLab CI Setup

Use the supported GitLab CI installation template from
[examples/.gitlab-ci.example.yml](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.gitlab-ci.example.yml). Its
pinned `ZERO_ONE_OPS_VERSION` default is the template compatibility version;
update it intentionally when upgrading to a later released version. This is an
include template: the root `.gitlab-ci.yml` must define `zeroone-ops-fix`
before `zeroone-ops-review` in its `stages` list.

Current job roles:

- `zeroone_ops_findings_sync`
  - finding sync for SonarQube and configured SARIF sources
- `zeroone_ops_ruff_sarif` and `zeroone_ops_mypy_sarif`
  - optional, repository-owned SARIF producers whose artifacts feed finding sync
  - the MyPy job requires a repository-owned JSON-to-SARIF converter at
    `MYPY_TO_SARIF_SCRIPT`; remove the job when MyPy is not configured
- `zeroone_ops_control_plane`
  - GitLab issue-mode policy processing, work-item recovery, and one
    remediation attempt, followed by one derived-summary refresh
- `zeroone_ops_work_items_sync_status`
  - lifecycle reconciliation before finding sync, so merged or closed merge
    requests converge before the next promotion decision
- `zeroone_ops_review`
  - merge request review note publication with no code changes

Recommended settings:

- run only on the default branch
- create a scheduled default-branch pipeline with `OPERATION=zeroone_ops`; use
  the same variable for an explicit GitLab web pipeline when operator follow-up
  is needed
- keep finding sync as a separate job from active remediation
- for GitLab issue mode, use one `zeroone_ops_control_plane` job after finding
  sync; schedule it at the desired cadence with `OPERATION=zeroone_ops`
- keep lifecycle reconciliation as a separate job from active remediation so it
  only owns post-merge-request lifecycle convergence
- use `resource_group` per workflow so overlapping runs of the same workflow do
  not collide
- override the job image `entrypoint` to `[""]`
- use `GIT_DEPTH=0`
- set a fixed git author/committer identity
- rewrite `origin` to use `GITLAB_TOKEN` for authenticated pushes
- set `ZEROONE_RUFF_SCAN_ENABLED=false` or
  `ZEROONE_MYPY_SCAN_ENABLED=false` when the matching optional producer is not
  configured; add a repository-owned SonarQube scanner job before finding sync
  when SonarQube analysis must run in the same pipeline
- keep `UV_VERSION` pinned when remediation validation commands use `uv`; the
  template installs it only in the remediation job

For review-only jobs, branch push credentials are not required because the
workflow only reads merge requests and writes merge request notes.

Optional MLflow tracing can be enabled in CI for OpenAI-backed runs. Keep this
off by default unless a reachable tracking server is configured for the
environment.

Recommended CI variables for a first review-tracing rollout:

- `ZEROONE_MLFLOW_ENABLED=true`
- `MLFLOW_TRACKING_URI=https://mlflow.example.internal`
- `MLFLOW_EXPERIMENT_NAME=zeroone-ops-review`
- `MLFLOW_HTTP_REQUEST_TIMEOUT=5`
- `MLFLOW_HTTP_REQUEST_MAX_RETRIES=1`

The timeout and retry settings are especially useful in CI so an unreachable
MLflow server does not stall review or remediation runs for too long.

For a lower-cost review setup:

- keep the review job manual on merge request pipelines
- rely on `CI_MERGE_REQUEST_IID` so the bot reviews only the current merge request
- set `review.max_changed_files` conservatively, for example `5`
- treat `review.supported_paths` as an optional allowlist; if it is omitted or
  empty, the review workflow considers all non-ignored changed paths in scope
- set `review.ignored_paths` for generated or otherwise low-value areas
- keep `review.max_findings_per_review` low so only the highest-signal findings are published

The retired `review.skip_draft_merge_requests` and
`review.max_review_feedback_retries` settings fail validation in v1. Remove them
before upgrading; see the [migration guide](migration-v1.md). Control draft-review execution
through provider CI rules instead. `review.publish_no_findings_note` is not a
supported setting.

Recommended first rollout order:

1. set `gitlab.control_plane_mode` to `issues` for GitLab installations
2. manually run `findings sync` on the protected default branch and inspect
   the policy and work-item issues
3. add one strict `/zeroone policy ...` comment to the policy issue and run
   policy processing
4. inspect one approved work item with `remediation run --dry-run`
5. manually run the provider's live control-plane/remediation workflow
6. run `work-items sync-status` after the resulting merge request or pull
   request is merged or closed
7. manually run `review` on one small change request
8. enable schedules only after all workflows behave as expected

## Expected Reconciliation Workflow Behavior

In normal `ci` mode, one reconciliation run should do the following:

1. load authoritative open work-item issues with linked change requests
2. fetch the current merge-request or pull-request state from the provider
3. decide one lifecycle outcome:
   - `completed` when the change request was merged
   - `blocked` when it was closed without merge and work remains
   - retain protected work when metadata is missing, inaccessible, or no longer matches
     stored traceability
4. update the authoritative work-item issue while preserving remediation
   metadata and provider labels
5. close terminal provider issues and refresh the derived summary

If no reconciliation-ready item remains, the run should exit cleanly with
`no_issue`.

## Common Outcomes

### No Issue Selected

This is expected when:

- SonarQube credentials are missing
- no open issues match the configured severity and type filters
- remaining issues point to files not present in the repository
- remaining issues are already represented by open bot merge requests
- remaining issues are excluded by v1 safeguards such as rename-style issue skipping

### No Merge Request Selected

This is expected when:

- GitLab credentials are missing
- no open merge requests exist
- open merge requests were already reviewed for the current head SHA

### Merge Request Reused

This is expected when:

- the predicted bot branch already has an open merge request

The bot should skip that issue and move to the next eligible one. If no other
issue qualifies, the run exits cleanly.

### Review Note Published

This is expected when:

- one merge request was selected
- review context was built successfully
- the LLM returned a valid structured review result
- GitLab note publication succeeded

The note should be a single summary comment, not multiple inline comments.

Issue-mode review projection remains best effort after note publication. Its
persisted repair evidence allows later retries without republishing the review.

### Run Failed

Look at:

- pipeline logs
- the final run summary
- `.zeroone-ops-state.json` if local state persistence is enabled in the repo

The failure record should tell you:

- stage
- message
- retry count
- failed validation command when relevant
- exit code when relevant

## Common Failure Modes

### Missing Configuration

Symptoms:

- run stops before issue selection or publish
- error mentions missing environment variables

Checks:

- confirm the CI variables exist
- confirm protected variables are available to the branch/pipeline context

### No OpenAI Output

Symptoms:

- analysis step reports no LLM backend configured

Checks:

- confirm `OPENAI_API_KEY` is present
- confirm `OPENAI_MODEL` is present
- confirm the repository is not accidentally using local fixture-only settings

### Patch Apply Failure

Symptoms:

- run fails during patch application

Checks:

- inspect the issue type
- confirm it is not a rename-style issue or another unsupported pattern
- confirm the repository content still matches the expected source around the target line

### Validation Failure

Symptoms:

- patch applies but validation fails
- run may retry once, then stop

Checks:

- inspect the failed command in the logs
- inspect whether the selected issue was actually low-risk enough for the current eligibility policy
- confirm the validation commands in the repository-specific `.zeroone-ops.json`
  are correct for the target repo

### Branch Push Failure

Symptoms:

- commit succeeds but publish fails

Checks:

- confirm `GITLAB_TOKEN` can push branches
- confirm the CI job rewrites `origin` to an authenticated URL
- confirm branch protections do not block the bot branch pattern

### Merge Request Creation Failure

Symptoms:

- branch is pushed but no merge request is created

Checks:

- confirm `GITLAB_TOKEN` has API access
- confirm `GITLAB_URL` and project identification are correct
- confirm the repository allows merge request creation from the bot token

### Review Context Failure

Symptoms:

- the review run fails before note publication
- the message mentions missing changed files or the merge request exceeding limits

Checks:

- confirm the merge request changes are present in the checked-out repository
- confirm the changed-file count is within the configured v1 review limit
- confirm review-supported paths are configured correctly if path filtering is enabled

### Review Note Publication Failure

Symptoms:

- review analysis succeeds but no note is created

Checks:

- confirm `GITLAB_TOKEN` can create merge request notes
- confirm the target merge request still exists and is open
- confirm `GITLAB_PROJECT_ID` / `CI_PROJECT_ID` match the repository being reviewed

## Recovery Steps

When a run fails:

1. identify the failure stage from the run summary or logs
2. correct the root cause
3. rerun the pipeline manually or wait for the next scheduled run

For a blocked work item, post its displayed recovery command after the current
failure was recorded. On both providers, comment directly on the affected
work-item issue. Older commands are ignored so a prior operator
decision cannot affect a later failure.

When an issue already has an open merge request:

1. review or close that merge request
2. rerun the bot only after deciding whether the issue should remain in scope

When a change request should no longer be managed by the bot:

1. close the merge request or pull request
2. requeue or dismiss the affected work item through its displayed operator
   command when appropriate
3. rerun only if the issue should still be considered eligible

## Debugging Guidance

Use CI solution artifacts only when you need extra debugging detail. They are
disabled by default in `ci` mode to reduce artifact churn.

If you need them temporarily:

- set `ZEROONE_OPS_WRITE_SOLUTION_ARTIFACTS_IN_CI=true`
- rerun the pipeline
- remove the override once debugging is done

## Validation Toolchain Images

The published ZeroOne Ops image is a thin bot runtime, not a general-purpose
project build image. It includes Python 3.13, Git, curl, and CA certificates.
The bot is installed under `/opt/zeroone-ops/.venv`; `/workspace` is the default
working directory. Its default user is `zeroone` (UID/GID `10001`), with
`HOME=/home/zeroone`.

Project-specific package managers, compilers, language runtimes, and test tools
are operator-owned. For example, `uv`, Node.js, Java, and native build dependencies
are not part of the base-image contract. The Python version bundled for the bot
is not a promise that every target project's Python requirement is satisfied.
Existing examples install uv in CI; an operator-owned derived image can instead
provide stable tooling before the job starts.

### Build A Derived Image

This Python example installs native compilation tools and the uv version used
by the GitLab template. Adapt those tools to the target repository; pin the base
to the exact release or RC being validated, and pin additional tool versions or
image digests according to your own supply-chain policy.

```dockerfile
ARG ZEROONE_OPS_VERSION
FROM ghcr.io/justinmelger/zeroone-ops:${ZEROONE_OPS_VERSION}

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

USER zeroone
ARG UV_VERSION=0.11.8
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" | sh
ENV PATH="/home/zeroone/.local/bin:${PATH}"
WORKDIR /workspace
```

Build and publish this image to your own registry. Supply the base version
explicitly, for example `--build-arg ZEROONE_OPS_VERSION=<validated-version>`;
use a distinct derived-image tag for each base/toolchain combination. Rebuild
deliberately when either changes. OS packages in this example follow the base
distribution's repositories; the example is not a reproducible-build guarantee.

Retain the inherited ZeroOne Ops entrypoint and bot environment. Switch to root
only for image-build installation, then restore the non-root user. Do not install
project dependencies into `/opt/zeroone-ops/.venv`, replace its Python packages,
or use an image build to run untrusted target-repository setup commands. Keep
repository dependencies in their own environment, such as `/workspace/.venv`.
Never bake registry tokens, provider tokens, or model credentials into image
layers; supply required credentials through protected CI secrets at runtime.

### Select The Image In CI

Use the derived image in the existing privileged remediation job:

- GitLab: replace the image on `zeroone_ops_control_plane`, or on
  `.zeroone_ops_base` if every bot job should use it. Retain `entrypoint: [""]`
  so GitLab can execute the job script.
- GitHub: replace `jobs.remediate.container.image` in the operations workflow.
  Apply the same image to other jobs only when those jobs need its tools.
- Remove redundant tool installation steps only after the derived image supplies
  those tools. Keep Git identity/authentication setup and existing job permissions,
  default-branch restrictions, scheduling, and serialization unchanged.

Replacing `ZERO_ONE_OPS_VERSION` alone does not select a custom registry image;
update the existing job's full image reference. Review jobs must not inherit
remediation dependency setup or validation just because they share an image.

The effective job user must be able to write the checkout, Git metadata, and its
tool caches. `/workspace` ownership in the image does not change the ownership
of a mounted checkout or the runner's actual checkout directory. Configure
runner permissions accordingly rather than making production jobs privileged
or defaulting the image to root.

### Verify Before Rollout

Run `zeroone-ops --help` and the required tool version commands inside the
derived image. Then run your configured setup/check commands against a disposable
checkout using the same user, mount permissions, credentials, and network access
as the intended CI job. Confirm private package registries are reachable without
printing credentials and that setup leaves real repository changes untouched.

Keep dependency setup and checks under `remediation.validation_setup_commands`
and `remediation.validation_commands`. They remain executable CI policy from the
trusted default branch. Installing a tool in the image does not configure or
run validation automatically. A review-only smoke test must not run those commands.
Finally, validate one complete remediation on each provider using the selected
image; a successful image build is not live workflow acceptance.

## Smoke Test Recipe

Use this recipe before you rely on the bot for unattended scheduled runs in a
new repository.

### Preconditions

Make sure the target repository has:

- a valid `.gitlab-ci.yml` based on
  [examples/.gitlab-ci.example.yml](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.gitlab-ci.example.yml)
- the published bot image reference pinned to a current release, such as
  `ghcr.io/<owner>/zeroone-ops:0.54.0`; use an immutable digest when the
  repository requires stricter supply-chain pinning
- a repository-specific `.zeroone-ops.json`, often copied from either:
  - [examples/.zeroone-ops.minimal.json](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.zeroone-ops.minimal.json)
  - [examples/.zeroone-ops.json](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.zeroone-ops.json)
- required CI variables set
- at least one open SonarQube issue that is:
  - low severity in the maintainability model
  - in a file that exists in the repository
  - within the current v1 rule allowlist
  - expected to require only one-file structured edits

### JSON Config Quick Guide

The repository-level `.zeroone-ops.json` has a small required core.

Required JSON fields:

- `base_branch`
- `remediation.target_branch`

Everything else in the JSON config is optional and falls back to application
defaults unless your repository needs custom behavior.

In GitHub and GitLab issue control-plane modes,
`remediation.max_active_work_items` defaults to `10` and bounds open approved,
in-progress, and review-feedback/revision work items across all finding sources.
Findings that exceed the limit remain backlog-only until a later sync finds capacity.
Active owned findings are not backlog and are not counted as new promotions on
repeat syncs. A failed or uncertain capacity-releasing transition retains its
reservation for that run; the sync warns and later runs can reconcile it.

New work uses promotion-time file/rule batching on both GitHub and GitLab.
`remediation.max_findings_per_work_item` defaults to `5` and accepts only strict
positive integers. A value of `1` prevents multi-member proposals. Existing
single-finding issues and frozen batch memberships remain unchanged.

Generate current target-branch reports before finding sync. The shared coordinator
refreshes member observations, applies policy/capacity decisions, and rechecks
ownership/dismissal before creation. Source priorities rank batches before
severity; one active batch consumes one work-item slot. Excess members stay in
aggregate backlog. Incomplete sources cannot establish absence. There is no
new enablement flag, migration, splitting command, or atomic reservation.

Fresh batch intake reads policy once, without creating or updating the policy
issue, and carries that snapshot through claim and execution. A failed lookup
withholds fresh batches, not independent single-finding work or recorded retry
and revision scope. Complete context and analysis accounting are mandatory:
no representative-only or partial batch change is published.

Batch issues show original, detected, absent, unknown-freshness, policy-excluded,
planned-targeted and recorded-attempt counts. Policy-dependent counts are marked
**not evaluated** when no explicit policy is supplied. Display tables show at
most ten members with 300-character message excerpts; collapsed machine state
retains all evidence. Targeted, absent, and merged are different facts.

A safely unstarted batch manually closed by an operator releases ownership;
reported members may create new work. Dismiss it instead to suppress exact
members. Closing protected/started work does not release ownership. Linked
request terminal states remain lifecycle-owned. Selection failures remain
blocked until an authorized operator corrects the cause and posts a new
`/zeroone remediation requeue` on the work-item issue. Observation refresh
never unblocks work automatically.

The complete serialized batch issue body and PR/MR description must fit a
60,000 UTF-8 byte **application** budget, not a claimed provider-native limit.
Oversized new proposals remain backlog-only with `projection_size_exceeded`;
existing updates retain previous authority and emit a bounded warning/failure.
Claim failure prevents execution and publication payload failure prevents push
or request publication. Evidence is never cut to fit; reduce the new-batch
limit or resolve the cause before retrying. There is no automatic splitting.

Batch analysis/edit prompts and schemas activate only for typed batch targets.
Review receives bounded attempt evidence only from unique verified work-item
linkage and evaluates the diff against it as untrusted claims, never proof.
Single-finding prompts and schemas retain their contracts.

For rejected batch analysis, **Latest Attempt** near **Next Action** distinguishes
model-requested manual handling from missing/inconsistent batch accounting and
unaddressable findings. It shows up to three explanations with recorded
file/rule/line locations; these are not claimed to be current checkout locations.
**Last Execution** retains up to ten explanations and collapsed technical
references, with explicit omitted counts. Unknown or truncated references never
infer a line. No edit is generated or published by the rejected attempt.
Inspect the explanation, linked request, and workflow logs before deciding on
manual correction or a new authorized requeue on the work-item issue. A failed
revision returns to `review_feedback_required`; its existing request is retained.
Earlier assessment evidence is labelled **Retained Change Rationale**, not a
claim produced by that failed attempt. Existing recovery clears the current
failure notice. CLI output includes the same category and bounded explanations
plus existing issue/request links. A reported `status=failed` does not change the
existing CLI exit-code contract; do not infer remediation success from job color.
Recorded publication retries and same-request revisions retain their original
targeted scope even after later scans show absence. Fresh operator-authorized
recovery alone can complete current all-absent work as `no_longer_detected`.
Before recording that completion, remediation rechecks the existing issue's
latest observations and execution ownership. If they changed or the write fails,
the run reports that completion was not applied or could not be confirmed.
Changed authority is retained without an overwrite; a failed provider write may
have an uncertain outcome and is not reported as successful completion. A missing/closed issue
is never recreated by this completion path. A dry run only previews the decision.
Batch request descriptions distinguish targeted members from verified resolution;
validation and change-rationale evidence remain separate.

Work-item issues and PR/MR descriptions use **Change Rationale** for the model's
current-behavior description, intended change, and explanation of why existing
behavior should be preserved. The section states: "Model-provided explanation;
not independent verification. See validation and review results." It is not an
approval, proof of correctness, or a validation result.

If automatic remediation stops at this step, the issue displays **Why remediation
stopped** and labels the **Last Execution** stage **Change rationale**. Missing
assessment evidence is shown as "No change rationale was available." Empty
records produce no rationale section. Internal `semantic_safety` fields and
failure-stage values remain unchanged in machine state and structured logs;
the gate still checks evidence structure and bounds, not semantic truth.
Historical free-text evidence is retained verbatim, with no bulk rewrite of
remote issues or change requests. New wording appears on normal rendering.

Internal intake withholds conflicting batch owners, including an old batch
reopened after replacement, and logs bounded issue references. It does not claim
either conflicting batch; unrelated work can still proceed. Execution projection
preserves sync's latest membership, observations, and selection evidence, while
retaining the frozen attempt targeted by analysis, retries, and revisions.

`remediation.source_priorities` optionally orders policy-eligible sources
before severity when capacity is constrained. Lower non-negative values are
higher priority; omitted sources use the neutral default `100`, preserving the
existing severity-first order when no mapping is configured.

Finding-sync dry runs evaluate local findings and policy without loading open
work items. Their output does not preview active-capacity decisions or
stale-item reconciliation.

This means:

- use the minimal example when you only need a working starting point
- use the fuller example when you want to pin validation commands, review
  limits, labels, or other repo-specific behavior explicitly
- credentials such as GitLab, SonarQube, and OpenAI tokens are still provided
  through environment variables or CI variables, not through this JSON file

Minimal valid example:

```json
{
  "base_branch": "main",
  "remediation": {
    "target_branch": "main"
  }
}
```

Fuller example:

- [examples/.zeroone-ops.json](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/.zeroone-ops.json)

Optional remediation change-request ownership:

- set `gitlab.merge_request_assignee_username` when created remediation merge
  requests should be assigned to a specific GitLab username for review
- set `github.pull_request_assignee_username` when created remediation pull
  requests should be assigned to a specific GitHub username for review

### Recommended First Test

Start with one intentionally simple issue, ideally something equivalent to:

- `python:S1125`
- one local file
- one exact text replacement

Do not use a rename issue or a fix that obviously needs multiple files.

### Steps

1. confirm the target repository pipeline can pull the `zeroone-ops` bot image successfully
2. confirm the bot job has access to:
   - SonarQube
   - OpenAI
   - GitLab push and merge request APIs
3. trigger the bot job manually instead of waiting for a schedule
4. watch the pipeline logs for:
   - issue count fetched
   - selected issue key
   - structured edit generation
   - diff rendered by bot
   - validation success
   - branch push
   - merge request created or reused
5. open the created merge request
6. verify the merge request description contains:
   - issue key
   - rule
   - severity
   - file
   - issue message
   - validation summary
   - bot-rendered diff note
7. inspect the diff and confirm it stays within one file
8. verify the branch name maps to the issue key and file path as expected

### Expected Healthy Outcome

A successful smoke test should produce:

- one selected remediation item
- one bot branch
- one merge request
- a diff limited to one file
- passing validation in the pipeline logs
- no duplicate merge request creation on an immediate rerun

### Recommended Follow-Up Check

After the first successful run:

1. rerun the pipeline once
2. confirm the existing issue is skipped because an open merge request already exists
3. confirm the bot either:
   - selects the next eligible issue, or
   - exits cleanly with `no_issue`

### Failure Signals That Should Block Rollout

Do not move to scheduled unattended runs yet if you see:

- rename-style issues being selected
- multi-file structured edits proposed
- validation failures on supposedly low-risk rules
- repeated attempts against the same open merge request
- merge requests whose diffs widen beyond the selected issue
- branch push or merge request creation auth instability

## Review Smoke Test Recipe

Use this recipe before enabling scheduled or manual GitLab MR review runs in a
repository.

### Preconditions

Make sure the target repository has:

- a valid `.gitlab-ci.yml` that can run `zeroone-ops review`
- required review variables set:
  - `GITLAB_URL`
  - `GITLAB_TOKEN`
  - `GITLAB_PROJECT_ID` or `CI_PROJECT_ID`
  - `OPENAI_API_KEY`
  - `OPENAI_MODEL`
- at least one open merge request with a small, reviewable diff

### Recommended First Review

Start with one merge request that:

- changes one or two source files
- has a small diff
- is not already reviewed by the bot
- is easy for a human to evaluate for note quality

### Steps

1. confirm the repository pipeline can pull the `zeroone-ops` bot image successfully
2. confirm the review job has access to:
   - GitLab merge request APIs
   - OpenAI
3. trigger the review job manually
4. watch the logs for:
   - open merge request count
   - selected merge request IID and head SHA
   - review context build success
   - review classification
   - note publication
5. open the target merge request
6. verify there is one deterministic AI review summary note
7. confirm the note is clearly one of:
   - findings present
   - no findings in this pass
8. rerun the review job immediately
9. confirm the unchanged MR revision is skipped cleanly

### Expected Healthy Outcome

A successful review smoke test should produce:

- one selected merge request
- one deterministic summary note
- a persisted reviewed revision keyed by MR IID and head SHA
- a clean skip on immediate rerun when the head SHA is unchanged

### Failure Signals That Should Block Rollout

Do not move to unattended review runs yet if you see:

- repeated notes on the same unchanged merge request revision
- review notes that are malformed or inconsistent in shape
- review runs failing to read merge request changes reliably
- comments being published when the run should have been a dry-run

## GitHub Review Workflow Example

For GitHub review smoke tests, start from:

- [examples/github-review.yml](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/github-review.yml)

The example is intentionally scoped to review only:

- GitHub pull request trigger
- summary-comment publication
- no remediation or control-plane workflow yet

Current config note:

- keep top-level `platform` set to `github`
- use the example workflow comments for the smallest valid review-only JSON
  shape

## GitHub Control-Plane Setup

Use [examples/github-operations.yml](https://github.com/JustinMelger/ZeroOne-ops/blob/main/examples/github-operations.yml) as
one installed control-plane workflow. It schedules finding sync, remediation,
and lifecycle convergence; processes policy comments only on the policy issue;
and processes recovery comments only on work-item issues.

Remediation processes at most one approved work item per run. Repository-scoped
workflow concurrency serializes live claims, so concurrent runs do not select
the same item.

Required workflow permissions:

- `contents: write` to push the remediation branch
- `issues: write` to claim and project the authoritative work item
- `pull-requests: write` to create or reuse the remediation pull request

## Pre-Release Checklist

Promotion-time file/rule batching is a
[proposed functional design](https://github.com/JustinMelger/ZeroOne-ops/blob/main/docs/design/functional/functional-design-remediation-batching.md),
not an available feature or an additional release gate. Current work items
remain single-finding; do not configure the proposed ten-member default.
The proposal creates new batches only and never migrates existing issues.
Any future operator deletion of old unstarted, unlinked issues would be optional
and lose their history; it would not guarantee that the next sync promotes a batch.

Before calling the target repository setup stable, confirm:

- the pipeline collects every configured finding source successfully
- the bot creates at most one branch and one provider-native change request per
  work item
- duplicate work items are skipped on rerun
- validation commands match the repository
- the provider token can push and create the required merge request or pull
  request
- operators know where to inspect failures and how to rerun safely
- the smoke test and immediate rerun both behave as expected
- finding sync and lifecycle reconciliation remain separate workflows
