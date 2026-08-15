# Functional Design: Finding File Grouping

## Status

Parked design. This contract records the intended boundary only; it does not
change current finding sync, work-item promotion, or remediation behavior.

## Goal

ZeroOne Ops should retain every normalized finding and its source provenance
while gaining a deterministic file-level inventory that later remediation
planning can use. A file group provides context; it is not evidence that the
findings describe the same defect or can be fixed together.

## Scope

The future grouping boundary receives normalized findings from every supported
source after source-local parsing and path canonicalization. It produces a
`FileFindingGroup` for each repository-relative file path containing one or
more findings.

Each group retains the complete normalized finding records, including their
stable identity, source identity, severity, title, location, remediation
context, and optional source metadata. Collection metadata remains beside the
collection rather than being copied into every group member.

Groups are deterministic:

- group by repository scope and canonical repository-relative path
- sort members by start line, end line, source ID, diagnostic code, then stable
  finding ID
- keep a finding with no usable repository-relative path outside file grouping;
  it remains an individual normalized finding and is never discarded

## Product Rules

File grouping is not deduplication. Findings from Ruff, MyPy, SonarQube,
Semgrep, or future sources remain distinct even when they share a file, rule,
message, or location.

File grouping is not a work-item rule. In the initial design it must not:

- replace individual stable finding identities
- change shared queueing, promotion, capacity, lifecycle, or dismissal rules
- create one work item, branch, or change request per file
- infer a shared root cause, symbol, or fix scope
- use an LLM or source-specific semantic clustering

Current one-finding work items and one-file remediation remain the active
product behavior until a later remediation-unit contract is implemented.

## Future Remediation Units

The later flow is intentionally layered:

```text
source adapters
  -> normalized findings
  -> file finding groups
  -> remediation-unit analyzer
  -> remediation units
  -> work items
  -> pull or merge requests
```

A remediation unit may contain one or more findings that are supported by a
single coherent change. Only that future unit, not a file group by itself,
would be eligible to become a work item.

The first analyzer must be conservative. It may begin by considering only
members with the same repository path, source, diagnostic code, and remediation
category. Cross-source grouping, symbol analysis, semantic equivalence, and LLM
clustering are deferred until operator evidence justifies them.

## Operator Experience

There is no operator-visible behavior change in this parked phase. A future
work item may show the individual findings that informed its remediation unit,
but it must preserve each source, rule, location, and finding identity for
inspection and lifecycle traceability.

## Acceptance Criteria for Future Implementation

- Every normalized finding remains represented exactly once in either a file
  group or the ungrouped inventory.
- Grouping is stable across equivalent source ordering.
- Existing finding IDs, source ownership, policy decisions, and work-item reuse
  remain unchanged until remediation-unit promotion is deliberately introduced.
- A file group alone cannot cause several unrelated findings to share a branch,
  work item, or change request.
