# Persistent Review Overview And Quality Evidence

## Status And Related Contracts

**Slice 1 implemented and automatically verified; live acceptance pending.** Persistent
publication is the implemented contract below. CI/JUnit/Cobertura reporting and
evidence-only refresh remain proposed for later slices, not supported behavior.
The **What Changed** summary below is a separate proposed follow-up, not part of
completed Slice 1 or an implemented report feature.
The **Reviewed Commit Context** UX slice is also proposed; current publication
still displays full head/base hashes without a provider-supplied commit title.
This document changes publication, not model judgment. Automated completion does
not establish live provider acceptance; keep those acceptance gates unchecked.

The [technical design](../technical/technical-design-review-overview.md) defines
storage, collection, and failure boundaries. The existing
[staged-review contract](functional-design-pr-review-staged-pipeline.md) remains
authoritative for candidate generation, precision, classifications, and inline
continuity. The [roadmap](../../roadmap.md#review-overview-design) tracks delivery.

## Purpose

Give developers and operators one reliable entry point on each GitHub PR or
GitLab MR. Reduce repeated full-summary comments and show finalized AI findings
alongside independently collected CI, test, and coverage evidence.

The overview is not approval, a merge gate, or proof of correctness. An AI
concern, a failed pipeline, and unavailable coverage are different signals.

## Overview And Discussions

- Maintain one managed overview per request, updating it after a completed review
  rather than posting another full summary.
- Show the reviewed commit, AI verdict/risk/confidence, accepted finding count,
  new/unresolved/resolved counts when continuity is available, and workflow links.
- Give the AI verdict its own prominent heading, with risk and confidence beneath
  it. Keep actionable findings, continuity counts, and next action visible. Put
  exact head/base hashes, workflow links, and prior-review framing inside collapsed
  **Review Details**, separate from recent history. Prior-review references are
  provenance, not active findings; preserve them without crowding the result.
- Link active findings to existing inline discussions. Findings without a usable
  inline location retain concise, actionable details in the overview.
- Keep existing inline creation, reuse, and resolved-finding behavior unchanged.
  The overview does not automatically resolve or reopen discussions.
- Retain a collapsed recent-review history with commit, classification, counts,
  and run link. Initially display at most five completed passes, including the
  current pass. Older displayed entries may be summary-only; label them as such.
  Disclose that history is bounded, not a complete audit archive.
- For verified remediation requests, link to the authoritative work-item issue.
  Requeue commands still belong there, never in the overview.
- The whole overview comment is bot-managed. Operator discussion belongs in
  replies or separate comments; do not promise preservation of edits inside it.

There is no second execution-status comment in the initial design. The overview
identifies the last completed review and the latest attempted run separately.
Failed or in-progress work must never be presented as a successful review of new
code. The initial slice updates on completion or a handled failure, not through
continuous progress polling.

The default installation remains a final-stage review: unit tests, integration
tests, and optional coverage aggregation finish before one review invocation
publishes the overview. Do not require an early AI review plus a second quality
job. Pending remains an availability state for an explicitly unfinished producer,
not the normal presentation for this installation pattern.

Model-context selection, durable recovery evidence, and visible history are
separate concerns. Changing `max_prior_review_passes` must not resize the provider
overview's history or remove its current recovery artifact. Initial overview
bounds are application-owned, without new operator tuning settings; see the
technical design for complete versus summary-only retention.

Slice 1 retains two complete completed passes and at most five completed summaries
including the current pass, independent of model-context limits. Its complete
serialized overview budget is 60,000 UTF-8 bytes, an application bound rather than
a provider limit. Oversize writes preserve the old overview and fail explicitly;
they do not silently discard required evidence or create overflow comments.
Only a verified bot-owned, request-matching overview is editable, following a
fresh body/head read. CI serialization reduces races but does not supply provider
compare-and-swap. Failed attempts remain separate from completed-pass authority.

### Proposed UX Slice: Reviewed Commit Context

**Proposed; not implemented.** Replace the prominent full head/base hashes with
a short, clickable reviewed SHA and the reviewed commit's title. Use the first
line of the commit message, not the PR/MR title or an AI-generated description.
For example:

```markdown
**Reviewed commit:** [cb8e089](<exact-commit-url>)
fix(review): verify installation identity and guard overview authority
```

Shorten long titles to at most 120 display characters with an explicit omission
indicator; the commit link provides the original message. Keep the full reviewed
SHA and comparison-base SHA in collapsed **Review Details**, and retain exact
identifiers in machine state. Short SHAs and commit titles are display labels,
never identities used for matching, writes, or recovery.

Fetch metadata for the exact completed review head, not the current branch tip,
target branch, or a synthetic checkout merge commit. Store it with that logical
review pass. A commit title describes only that commit; it is not a summary of
the entire PR/MR. Keep the proposed **What Changed** section separate.

Metadata lookup is best effort. If it fails, returns mismatched commit identity,
or historical records lack a title, show the short reviewed SHA without inventing
a label. Missing metadata does not fail review, change its verdict, or weaken
ownership checks. Reuse and recovery preserve stored metadata without additional
model calls or metadata backfill reads. Failed attempts leave the earlier
completed commit label intact. Do not infer an "up to date" badge merely because
the overview was regenerated.

Deliver this as a separate bounded UX slice: provider metadata lookup, optional
pass-local persistence, shared rendering, and GitHub/GitLab parity tests. Include
new-head updates, same-SHA and fresh-workspace reuse, missing historical fields,
lookup failure, mismatched SHAs, escaping, and long/Unicode titles. Implementation
and live acceptance remain unchecked; report-slice numbering is unchanged.

### Proposed: What Changed

**Proposed; not implemented.** Add a short **What Changed** section before the AI
verdict, with one to three factual bullets describing the current reviewed diff
between its pinned comparison base and head. Prefer two or three bullets when
useful; do not pad a small change merely to fill the section.

Keep this separate from the review-outcome summary, findings, Change Rationale,
and quality evidence. A description of a change is not approval, proof that a
finding was fixed, or evidence that validation passed. Describe supplied code and
diff evidence, not unsupported claims copied from the PR/MR title or description.
Do not claim full-branch coverage when review inputs are filtered or truncated;
show a short reviewed-scope limitation when appropriate.

For example, a review of the persistent-overview implementation could show:

```markdown
### What Changed
- Replaces per-review summary comments with one persistent overview.
- Retains bounded review history and pending recovery evidence.
- Adds authenticated identity lookup for GitHub installation tokens.
```

Generate this description within an existing review call, not through another
model stage or additional repository retrieval. Store it with the completed
artifact. A successful review of a new head may replace it with a description of
that head's full reviewed diff, not merely the latest push. Same-SHA reuse,
projection repair, comment recreation, and future quality-only refresh preserve
the stored description without another model call or logical review pass.

Historical artifacts without this field remain valid. Omit the section when no
usable description is available; never invent one from the verdict, confidence,
old history rows, or request title. A failed attempt must not replace the earlier
completed description with a claim about unreviewed code.

Acceptance covers summaries with and without findings, limited review scope,
missing historical fields, escaped repository-controlled text, new-head updates,
and unchanged descriptions during reuse and recovery on both providers. This
follow-up requires design review before implementation and does not reopen the
completed Slice 1 checklist or renumber the reporting slices.

### Clear Findings And Next Actions

The overview should answer: what commit was reviewed, what needs attention, why,
and where the operator should look next. Use plain-language labels and a concise
state-derived next action; do not make readers interpret counts or risk alone.

For a finding with a usable discussion link, show its severity, accepted title,
location, and discussion link. Keep evidence, impact, and suggested follow-up in
the self-contained inline discussion rather than repeating its impact in the
overview. For a summary-only finding or an unusable discussion link,
render the same accepted evidence directly in a bounded structured block:

```markdown
### Forward the caller's timeout to the HTTP request
Location: src/client.py:42-48
What changed: The function accepts timeout, but the request still calls session.get(url).
Why it matters: The supplied deadline is ignored; callers cannot rely on that contract.
Suggested next step: Forward timeout to the HTTP request.
```

This is fictional illustration, not a finding about this repository. These labels
organize existing title/evidence/explanation/follow-up fields; the renderer must
not add claims, infer root cause from test results, or rewrite finding meaning.
If accepted evidence is unclear, that requires a separate review-quality change,
not another summarization stage hidden in presentation.

## Quality Signals

**Proposed, not implemented in Slice 1.** The rest of the quality-evidence sections
describe later delivery; Slice 1 does not collect quality evidence.

Quality reporting is optional. With no configured reports, the review continues
to work without an empty Quality Checks section or an unconfigured-report notice.
Place the compact disclaimer “AI review does not replace CI checks or merge
approval.” in a footer below findings, next action, and supporting history.
When reporting is configured, show a dedicated **Quality Checks** section;
missing, stale, malformed, or failed expected reports remain visible there.

| Signal | Meaning |
| --- | --- |
| CI job status | Provider CI execution state for the explicitly identified producer, not inferred from test counts. An overall pipeline result is shown only when separately supplied. |
| Tests | Passed, failed, errored, and skipped results from configured JUnit XML suites. Zero collected tests is explicit, not a green test result. |
| Overall line coverage | Covered executable lines divided by measured executable lines for the declared coverage scope. |
| Coverage movement | Difference in percentage points between comparable reports at identified head and comparison-base commits. |
| Changed-code line coverage | Coverage of reported executable added/modified lines in the pinned diff, with unmeasured scope disclosed. |

Start with JUnit XML and Cobertura XML. Operators produce reports in existing CI
jobs and provide explicit report paths and producer metadata through CI wiring.
ZeroOne does not discover arbitrary job artifacts, execute additional tests,
install dependencies, or require Codecov or another hosted service.

Ship ready-to-use GitHub Actions and GitLab CI installation examples. Operators
primarily configure report paths/groups and keep their own test commands. The
supported templates generate the manifest through a maintained CI helper, wire
explicit producer artifacts, and preserve reports after test failures; operators
should not hand-write JSON or manifest-generation scripts. ZeroOne itself does
not search for or download arbitrary artifacts.

A versioned CI evidence manifest identifies the reports, producer jobs/attempts,
tested commits, groups, and expected suites/shards. It is an explicit CI handoff,
not a claim that an arbitrary file proves successful execution. Report contents
cannot supply their own trusted provenance.

Report analysis is structural, not AI: parse test outcomes, validate completeness
and identity, and calculate coverage from explicit measurements. No model reads
the reports, invents missing metrics, diagnoses failure causes, or changes their
status. This verifies report consistency, not whether the producer's tests are
correct or its execution claims are independently true.

Show source links and tested SHAs. Reports are evidence from their producer, not
independently verified test execution. A passing test report can coexist with a
failed job, for example when another validation step failed.

### Multiple Test Stages

Unit and integration jobs are separate named report groups, each with its own
producer status, attempt, tested SHA, and JUnit/coverage reports. Identical report
basenames are allowed, but CI must namespace their artifact names and download
paths so one stage cannot overwrite another:

```text
artifacts/review-quality/manifest.json
artifacts/review-quality/unit/junit.xml
artifacts/review-quality/unit/coverage.xml
artifacts/review-quality/integration/junit.xml
artifacts/review-quality/integration/coverage.xml
artifacts/review-quality/combined/coverage.xml
```

Show unit and integration test results separately. Combined test counts are
optional and require explicitly disjoint suites with no ambiguous duplicate
cases; do not call a sum of matrix/repeated executions a unique-test count.

For initial support, CI may use its native coverage tool to combine raw coverage
measurements and produce one canonical combined Cobertura report. ZeroOne does
not combine per-stage percentages or execute tool-specific coverage aggregation.
Stage-specific coverage remains separately labeled; without a declared combined
report, do not infer overall coverage from the stage reports.

The manifest declares the combined report's required contributing groups and
producer attempts. All inputs must match the tested commit and compatible
measurement scope/settings. Missing, skipped, canceled, or incomplete required
stages make combined coverage incomplete/unavailable, not a complete unit-only
result. A failed test job with complete valid measurements can still contribute;
its failure remains visible independently of coverage availability.

Illustrative overview:

| Signal | Result |
| --- | --- |
| Unit tests | 118 passed; producer job passed |
| Integration tests | 20 passed, 1 failed; producer job failed |
| Combined line coverage | 84.2%; measured from both declared stages |

If integration never runs, replace its row with the producer's skipped or
unavailable status and mark combined coverage incomplete. Retain valid unit
results without presenting them as the entire pipeline's results. Provide this
multi-stage pattern in both supported installation examples.

### Availability And Freshness

Use the following human-facing states consistently:

Availability and outcome are separate axes: an available, complete test report
can report failed tests. Do not collapse a failed producer, missing evidence, and
a failing test case into the same underlying state.

- **Not configured:** the operator did not enable this report group.
- **Pending:** the identified producer has not finished; no successful result yet.
- **Available:** valid, complete evidence correlated to the expected commit/scope.
- **Failed:** the producer failed or the report contains failing/errored tests;
  display those facts separately rather than replacing one with the other.
- **Unavailable:** expected evidence is missing, inaccessible, or lacks provenance.
- **Malformed:** parsing or structural validation failed; no usable metric.
- **Incomplete:** declared suites/shards or required coverage scope are missing or
  conflicting. Display any partial counts as partial, not a complete result.
- **Stale:** evidence belongs to another commit or an older producer attempt.
- **Not applicable:** a valid coverage report has no measured executable changed
  lines; do not display 100% for a zero denominator.

Never substitute zero coverage for missing evidence. A missing base report does
not hide valid head coverage, but prevents a movement claim. Base/head comparison
requires the same declared scope and compatible measurement settings.

The initial contract requires exact reviewed-head correlation. Reports from a
synthetic merge commit are not silently relabeled as head results: show the
tested commit and explain that head evidence is unavailable. Operators can wire
a producer checked out at the reviewed head. Base evidence must match the pinned
comparison base, not whichever target-branch build happens to be newest.

## Repeated Runs And Failure Behavior

- A successful review of a new head updates the same overview and adds one
  logical review pass to bounded history.
- A same-SHA rerun reuses the accepted review, may refresh quality evidence, and
  creates no model calls, duplicate overview, inline comments, or review pass.
- CI invokes the existing review workflow after report producers finish, including
  failed producers when artifacts are available. A later invocation can refresh
  the same SHA. No background poller, new command, or model rerun is required.
- An older run cannot knowingly replace evidence for a newer request head or
  producer attempt. A changed head withholds publication and reports the reason.
- Quality collection or parsing failure changes only the quality section and
  warnings, never the accepted findings, verdict, or work-item eligibility.
- Preserve normal review-publication failure semantics. Failure to create/update
  the authoritative overview is not reported as successful review publication.
- A failed review may update an existing overview's execution notice when safe,
  but retains the earlier completed review under its original SHA. With no prior
  overview, do not manufacture an authoritative review pass from the failure.
- Missing or ambiguous bot ownership withholds updates with an actionable error.
  Do not overwrite human comments or create another overview to bypass ambiguity.
- Existing legacy review summaries remain readable history; do not bulk edit or
  delete them. The first new overview can use their verified continuity evidence.

## Illustrative Overviews

Values and links below are examples, not measured project results. Production
output supplies provider-native commit, run, source-report, and finding links.

### Successful Review

```markdown
## ZeroOne Ops Review
Last completed review: abc1234 | Verdict: No findings | Risk: Low
No actionable findings in the reviewed scope. This is not merge approval.

| Quality signal | Result |
| --- | --- |
| Test job | Passed - view run |
| Tests at abc1234 | 118 passed, 0 failed, 0 errors, 2 skipped |
| Overall line coverage | 88.1% |
| Compared with base def5678 | 87.4% -> 88.1% (+0.7 percentage points) |
| Changed-code line coverage | 92.0% of measured executable changed lines |

Recent review history and report provenance are collapsed below.
```

### General Overview With Reports

This and the following example show the same AI finding. Report availability
changes the quality section and next action, not the finding or its severity.

```markdown
## ZeroOne Ops Review
Reviewed commit: abc1234 | Comparison base: def5678 | View review run
AI result: Concern | AI risk: Medium | 1 active finding
Next action: Inspect the finding and the failed integration test.

### Active Findings
1. Forward the caller's timeout to the HTTP request - src/client.py:42-48
   The supplied deadline is ignored. View finding discussion.

### CI And Test Evidence
| Signal | Result |
| --- | --- |
| Unit test job | Passed - view producer run |
| Unit tests at abc1234 | 118 passed, 0 failed, 0 errors, 0 skipped |
| Integration test job | Failed - view producer run |
| Integration tests at abc1234 | 20 passed, 1 failed, 0 errors, 0 skipped |
| Combined line coverage | 84.2%; complete measurements from both declared stages |
| Compared with base def5678 | 83.5% -> 84.2% (+0.7 percentage points) |
| Changed-code line coverage | 90.0% of measured executable changed lines |

Tests, coverage, and AI judgment are independent evidence, not merge approval.
Recent review history and report provenance are collapsed below.
```

### General Overview Without Reports

```markdown
## ZeroOne Ops Review
Reviewed commit: abc1234 | Comparison base: def5678 | View review run
AI result: Concern | AI risk: Medium | 1 active finding
Next action: Inspect the finding. Test and coverage status are not known here.

### Active Findings
1. Forward the caller's timeout to the HTTP request - src/client.py:42-48
   The supplied deadline is ignored. View finding discussion.

### CI And Test Evidence
Not configured. No test or coverage result is inferred from the AI review.

Recent review history is collapsed below.
```

Missing configured reports use unavailable/incomplete wording instead of the
not-configured message. An available CI status can still be shown independently
when test and coverage reports are not configured. Clean AI reviews without
reports say no actionable findings in the reviewed scope, not that tests passed.

### Findings Present

```markdown
## ZeroOne Ops Review
Last completed review: abc1234 | Verdict: Concern | Risk: Medium
2 active findings: 1 new, 1 unresolved. Since the previous review: 1 resolved.

- New: Missing authorization check - view inline discussion
- Unresolved: Request timeout is ignored - view inline discussion

Test job: Passed. Tests: 118 passed, 2 skipped. This does not dismiss AI findings.
For this remediation request, operator commands belong on the linked work-item issue.
```

### Missing Comparison Baseline

```markdown
Overall line coverage at abc1234: 88.1%.
Coverage movement: Unavailable - no matching report for base def5678.
No increase or decrease is inferred from a different target-branch build.
```

### Failed Tests

```markdown
AI review at abc1234: No findings.
Test job: Failed - view run.
Tests: 116 passed, 1 failed, 1 error, 2 skipped.
The AI verdict is unchanged; CI evidence independently reports failures.
```

### Stale Reports

```markdown
AI review at abc1234: Concern - 1 active finding.
Tests and coverage: Stale - supplied reports were produced for 999aaaa.
Current-head quality results are unavailable. View the identified producer run.
```

### Failed Review Execution

```markdown
Latest review attempt at bbb2222: Failed - view run.
Last completed AI review remains at abc1234: Concern - 1 active finding.
That result does not review bbb2222. Quality evidence is labeled by its own tested SHA.
```

## Acceptance And Delivery

| Scenario | Required outcome |
| --- | --- |
| First review, later changed head | One overview, preserved inline behavior, separate immutable logical passes. |
| With/without reports | Same finalized finding meaning, clear location/impact/next action, independent quality section, and no inferred test pass when reports are absent. |
| Fresh CI workspace | Recover current/prior review and repair evidence from verified provider-managed state. |
| Same SHA with newer reports | Refresh quality only, preserving artifact, pass identity, inline references, and pending projection repair. |
| Stale run, force push, duplicate markers | Withhold unsafe replacement; no blind overwrite or duplicate creation. |
| Missing/malformed/incomplete reports | Honest availability state; no invented pass, zero coverage, or AI classification change. |
| Unit/integration stages | Namespaced artifacts, independent job/test results, no duplicate totals or averaged coverage; missing required contributors cannot produce complete combined coverage. |
| Base mismatch or scope mismatch | Head metrics may remain visible; no coverage delta. |
| Inline or projection failure | Existing warning/repair behavior remains meaningful with a stable overview URL. |
| GitHub/GitLab and dry runs | Equivalent semantics; dry runs make no provider writes. |

Deliver separately: persistent overview/continuity, CI and JUnit evidence refresh,
then Cobertura coverage comparison. Slice 1 automated implementation is complete;
live provider acceptance and later slices remain unchecked until independently
reviewed and verified.

The persistent overview is a complete, independently shippable improvement
without report integration. Live-validate overview updates, fresh-workspace
continuity, and partial-publication recovery on both providers before starting
the report integration slice. Do not hold that delivery for the reporting roadmap.

Next validate the smallest practical JUnit installation on GitHub and GitLab,
including failed/missing test evidence and same-SHA refresh. Working installation
examples must demonstrate that operators mainly supply paths, not custom manifest
scripts. Only after that acceptance should coverage integration proceed.

Evaluate presentation clarity separately from finding quality. A cleaner overview
does not establish better defect detection or justify stronger AI claims. This
initiative is a review overview, not a CI analytics platform or a Codecov replacement;
trend dashboards and broad format/tool compatibility remain outside it.

## Non-Goals

No finding-adjudication prompt changes, specialist reviewers, model/provider
migration, Tree-sitter, new merge gates, shell-based investigation, automatic discussion resolution,
developer-feedback ingestion, or changes to remediation validation. Quality
reports are not new intake findings and are not added to model prompts.
The proposed **What Changed** follow-up is limited to extending an existing
call's descriptive output instructions and schema; it adds no model stage and
does not change finding judgment.
