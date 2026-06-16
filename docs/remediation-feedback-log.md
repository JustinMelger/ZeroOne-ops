# Remediation Feedback Log

Use this log during live testing to capture concrete remediation workflow
feedback and turn it into prompt changes, validation changes, remediation logic,
operator handoff, or no change.

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

- active remediation feedback
- recently patched remediation feedback still awaiting validation
- a short validated/closed tail only when it still helps current rollout work

## Open Defects

### June 2026 Active Issues

- Issue: Remediation can introduce a new library import without ensuring the
  dependency is installed
  - Reported: `2026-06-16`
  - Status: `open`
  - Last checked: `2026-06-16`
  - Example: remediation replaced synchronous file loading with
    `aiofiles.open(...)` and added `import aiofiles`, but runtime failed
    because the library was not installed
  - Request: add an explicit dependency-handling plan when remediation
    introduces new imports, including checking whether the package already
    exists, deciding whether dependency changes are allowed, and preferring
    standard-library or already-installed alternatives when not

## Recently Patched

### Remediation Prompt And Workflow Quality

- Issue: Remediation-created merge requests should use conventional-commit-style
  titles
  - Reported: `2026-05-06`
  - Status: `patched`
  - Last checked: `2026-06-16`
  - Request: use deterministic conventional-commit-style remediation MR titles
  - Patched in: remediation MR title standardization

- Issue: Generated remediation helpers should follow repo type-hint and
  docstring conventions
  - Reported: `2026-05-06`
  - Status: `patched`
  - Last checked: `2026-06-16`
  - Request: when remediation introduces new helpers or functions, follow
    repository conventions for type hints and docstrings
  - Patched in: remediation prompt hardening plus repo-guidance integration

- Issue: Repository guidance reached remediation prompts but not the main
  remediation execution seam
  - Reported: `2026-06-15`
  - Status: `patched`
  - Last checked: `2026-06-16`
  - Request: live remediation execution should use the same
    repository-guidance context path as the dashboard-prebuilt path
  - Patched in: remediation context-builder wiring and boundary tests

- Issue: Dashboard-backed remediation dropped `issue_type`, `component`, and
  `project`
  - Reported: `2026-06-15`
  - Status: `patched`
  - Last checked: `2026-06-16`
  - Request: keep producer metadata end to end through dashboard item,
    remediation work item, execution target, prompts, and MR publishing
  - Patched in: dashboard normalization and execution-target metadata flow

## Validated / Closed

- Issue: None currently
  - Status: `closed`
  - Last checked: `2026-06-16`
  - Note: keep this section short and only add entries once live remediation
    feedback confirms the patched behavior
