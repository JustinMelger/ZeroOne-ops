# Technical Design: Finding File Grouping

## Status

Parked design. No production integration is planned by this document alone.

## Boundary

File grouping belongs immediately after source-local intake has produced
`NormalizedFinding` values and before any future remediation-unit analysis. It
is a neutral finding-domain concern, not a SARIF concern: SonarQube and every
future adapter converge at the same boundary.

```text
source transport -> source adapter -> NormalizedFinding
                                      |
                                      v
                           FileFindingGroupingService
                                      |
                                      v
                            FileFindingGroup inventory
                                      |
                                      v
                       future RemediationUnitAnalyzer
```

The current finding-sync workflow continues to consume individual
`NormalizedFinding` values. Introducing a group inventory must not change that
route until a separate remediation-unit rollout is approved.

## Proposed Model

The derived model should preserve existing normalized records instead of
duplicating their fields:

```python
class FileFindingGroup(BaseModel):
    repository_scope: str | None
    repository_path: str
    findings: tuple[NormalizedFinding, ...]
```

`repository_scope` is supplied by the collection/workflow context when a
repository identity is available. The grouping key is
`(repository_scope, repository_path)`. `repository_path` must already be a
safe canonical repository-relative path; the grouping service must not repair,
resolve, or accept raw source paths.

The group has no persisted ID or lifecycle state. It is derived from one intake
inventory and may change as findings appear or disappear. `finding_id` remains
the only stable persistence and continuity identity at this layer.

Findings without a usable path are returned in an explicit ungrouped collection
alongside file groups. They are not assigned to a synthetic file group and are
not dropped.

## Deterministic Algorithm

`FileFindingGroupingService.group()` should:

1. Accept one normalized collection plus its repository scope.
2. Partition findings with a repository path by `(repository_scope,
   repository_path)`.
3. Return each group in lexical key order.
4. Sort members by `line_start`, `line_end`, `source_id`,
   `remediation_context.diagnostic_code`, and `finding_id`, treating missing
   values as deterministic terminal values.
5. Return pathless findings in the same stable member order as an ungrouped
   inventory.

The service must not inspect `source_metadata` for workflow decisions, merge
findings, select a representative finding, or change collection ownership.

## Integration Rules

When implemented, the initial group inventory may be supplied as bounded
context to a later remediation planner. It must not directly replace these
existing contracts:

- `NormalizedFinding.finding_id` for upsert and continuity
- source ownership and stale reconciliation
- shared policy evaluation and promotion capacity
- provider-local work-item persistence
- one-file patch application and validation scope

The future `RemediationUnitAnalyzer` is the only component allowed to convert a
file-group inventory into a multi-finding remediation candidate. Its output
must be explicit about its member finding IDs and still satisfy the existing
repository and patch-scope safety rules.

## Deferred Decisions

The following require a separate design before implementation:

- compatibility rules for members of the same remediation unit
- whether source/rule/category compatibility is mandatory in the first unit
  analyzer
- how an active, dismissed, or completed unit responds when group membership
  changes on a later sync
- work-item identity, title, and operator presentation for multi-finding units
- promotion capacity accounting for units rather than individual findings
- any symbol-level, cross-source, or model-assisted semantic grouping

## Future Tests

The future pure grouping slice should cover path partitioning, stable ordering,
source-order independence, pathless findings, and preservation of every member
record and collection metadata. A later remediation-unit slice must add
separate lifecycle, promotion, provider persistence, and one-file safety tests.
