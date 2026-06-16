# Review Bot Feedback Log

Use this log during live testing to capture concrete workflow feedback and turn
it into prompt changes, context changes, regression tests, or no change.

This file is intended to stay operational:

- `open`
  - active issue still under investigation or waiting for implementation
- `patched`
  - implemented in code, still awaiting live-validation confidence
- `validated`
  - confirmed working in live usage
- `closed`
  - no longer an active rollout concern

Keep this file focused on:

- active feedback
- recently patched feedback still awaiting validation
- a short closed/validated tail only when it still helps current rollout work

## Open Defects

### June 2026 Active Issues

- Issue: Repository guidance code-quality concerns are not reliably surfaced in
  candidate generation
  - Reported: `2026-06-11`
  - Status: `open`
  - Last checked: `2026-06-16`
  - Example: a merge request containing poor-quality Python code and an
    incorrect `if name == "main":` guard still returned `no_findings`, even
    though repository guidance emphasized clarity, safety, and small testable
    changes
  - Request: keep candidate and precision focused on real regressions, but
    continue collecting concrete examples of guidance-backed code-quality misses
    before broadening the pipeline

- Issue: Continuity misses a clear persisted finding when no overlap candidate
  is generated
  - Reported: `2026-06-16`
  - Status: `open`
  - Last checked: `2026-06-16`
  - Example: MR `!431` treated `UK/ROI details name fallback indexes an empty
    types list` as `new_in_this_pass` while marking the earlier
    `UK/ROI details name fallback can index empty types` finding as
    `no_longer_present`, even though the file, symbol, region, and underlying
    defect were the same
  - Request: overlap-candidate generation should catch near-identical persisted
    findings even when title or `issue_kind` wording drifts slightly

- Issue: The same underlying finding received different severity
  classifications across passes without stronger evidence
  - Reported: `2026-06-16`
  - Status: `open`
  - Last checked: `2026-06-16`
  - Example: `Vehicle lookup country map now silently defaults to empty` was
    first classified as `low`, then follow-up wording changed and severity
    became `medium` without materially stronger evidence
  - Request: severity should stay stable across follow-up passes unless the
    newer pass has materially stronger evidence or more concrete supported-path
    impact

### Review Output

- Issue: Unsupported path treated as regression
  - Reported: `2026-04-17`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: review assumes a `None` or missing-input path even though the
    visible schema forbids it
  - Request: stay stricter about supported-path evidence before calling
    something a regression

- Issue: Config/runtime shape overclaimed
  - Reported: `2026-04-17`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: review treats a config-derived symbol as a mapping/object even
    though runtime resolution is unclear or scalar
  - Request: prefer narrower runtime claims unless the visible code proves the
    resolved shape

- Issue: Code smell overstated as runtime bug
  - Reported: `2026-04-17`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: dead fallback logic or redundant cleanup gets described as a real
    supported-path regression without proof
  - Request: keep these as smell/maintainability concerns unless a real runtime
    path is visible

- Issue: Too verbose
  - Reported: `2026-04-17`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: the same point gets repeated across summary, evidence, and
    follow-up
  - Request: keep published notes shorter and less repetitive

### Review Continuity / Stability

- Issue: Same-SHA review instability
  - Reported: `2026-04-20`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!376` / `e47ba30b9e642e4ae4ae614fac15b0f851480a25`
  - Request: same-SHA reruns should stay much closer to one accepted finding
    set and verdict

- Issue: Missing inheritance or base-schema context
  - Reported: `2026-04-20`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!376` / `0bf395931f2e712326d6ddff75f0484e0fa3fc1a`
  - Request: shared base classes or inherited request fields should not be
    missed when they materially affect the review claim

- Issue: Test inconsistency overstated as runtime regression
  - Reported: `2026-04-20`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!96` / `e9a9a7c221c3480a1d671c449b8219d6fb755449`
  - Request: changed/removed test skips alone should not be treated as
    production runtime proof

- Issue: No-findings explanation leaks pipeline internals
  - Reported: `2026-05-03`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!176`, `!175`, and `!112` reruns
  - Request: keep staged-review mechanics out of developer-facing clean-pass
    notes

- Issue: Prior concern incorrectly counted as new
  - Reported: `2026-05-03`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!176` / `ec42036e45009d2a4167c267c0015b7b41e19874`
  - Request: follow-up continuity should stop counting semantically retained
    concerns as new

- Issue: Prior concern likely mismatched because weak title-derived identity drifted
  - Reported: `2026-05-03`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!178` / `ef4cdd90be87bcd4f48b293de1cedd8d4f879a10`
  - Request: keep hardening continuity matching when wording drifts but the
    concern is the same

- Issue: Response-body truth overstated as HTTP response semantics
  - Reported: `2026-05-03`
  - Status: `open`
  - Last checked: `2026-06-15`
  - Example: `!112` / `6240d3b6d9386bb4af0c72bfd7a3277fc600fa4b`
  - Request: distinguish payload/body truth from HTTP-status claims unless the
    code directly proves both

## Recently Patched

### Review Architecture / Quality

- Issue: Summary introduced unproven concern
  - Reported: `2026-04-17`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: keep summary claims bounded to accepted findings
  - Patched in: staged reconciliation, artifact building, validator gating

- Issue: Repeated review does not acknowledge earlier review clearly enough
  - Reported: `2026-04-18`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: repeated reviews should read as continuity-aware follow-ups
  - Patched in: staged continuity support and overlap-aware follow-up wording

- Issue: Supported-path contract change overstated
  - Reported: `2026-04-20`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Example: `!98` / `94fed6081726196e738c4952c20a73b6b888aab4`
  - Request: keep contract findings but narrow the pre/post behavior claims

- Issue: Verdict/reason contradiction
  - Reported: `2026-04-20`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Example: `!382` / `9b2b597fe38ed7ae9249194d2293505d07fb9c8f`
  - Request: never publish a clean verdict with contradictory actionable
    rationale

- Issue: No-findings summary/reason still describes regression
  - Reported: `2026-04-22`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Example: later confirmed again on `!389` and `!390`
  - Request: downgrade contradictory artifacts instead of publishing them

### June 2026 Feedback

- Issue: Valid manufacturing-year mapping bug was filtered out
  - Reported: `2026-06-10`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: keep directly supported added-code defects even when reachability
    is not yet proven

- Issue: Same finding treated as both `new_in_this_pass` and `no_longer_present`
  - Reported: `2026-06-10`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: continuity matching should not split the same concern across both
    buckets

- Issue: Repository guidance style/readability concerns disappeared instead of
  surfacing as non-actionable notes
  - Reported: `2026-06-15`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: preserve repo-guidance-backed non-actionable style concerns as
    `Style Observations (Repository Guidance)` rather than dropping them or
    smuggling them into rationale

- Issue: Remediation repository guidance reached prompts but not the main
  remediation execution seam
  - Reported: `2026-06-15`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: live remediation execution should use the same repository-guidance
    context path as the dashboard-prebuilt path

- Issue: Dashboard-backed remediation dropped `issue_type`, `component`, and
  `project`
  - Reported: `2026-06-15`
  - Status: `patched`
  - Last checked: `2026-06-15`
  - Request: keep producer metadata end to end through dashboard item,
    remediation work item, execution target, prompts, and MR publishing

## Validated / Closed

- Issue: Contract change valid
  - Reported: `2026-04-17`
  - Status: `validated`
  - Last checked: `2026-06-15`
  - Note: keep as a positive reference pattern for real supported-path review
    findings

- Issue: Header tone too robotic
  - Reported: `2026-04-17`
  - Status: `validated`
  - Last checked: `2026-06-15`
  - Note: replaced with simpler conversational wording
