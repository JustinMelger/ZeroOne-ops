# ZeroOne Ops Finding Ingestion Technical Design

## 1. Scope

This document defines the technical design direction for moving ZeroOne Ops
from source-specific discovery into provider-neutral finding ingestion.

The immediate goal is not to replace the current SonarQube intake path in one
step. The goal is to introduce a stable ingestion boundary that:

- keeps current Sonar-backed behavior working,
- allows one additional dogfooding source on this repository,
- makes later sources such as SARIF, workflow failures, coverage, or
  tool-specific JSON adapters a normal extension path instead of another
  architecture rewrite.

This design is specifically about finding ingestion. It is not a redesign of:

- review transport,
- remediation execution,
- dashboard rendering,
- GitHub or GitLab control-plane storage.

## 2. Problem

Today the intake side of the product is still source-shaped:

- the active production path is SonarQube-first,
- remediation models and dashboard sync still carry Sonar-oriented assumptions,
- adding another source risks turning into another source-specific workflow
  branch instead of a shared ingestion model.

That creates three problems:

1. extension cost
   - every new source risks touching dashboard and remediation logic directly
2. provider confusion
   - repository platform and finding source become easy to conflate
3. dogfooding limits
   - GitHub control-plane and remediation paths are harder to validate on this
     repository without SonarQube access

## 3. Design Goals

- Introduce one provider-neutral internal finding contract.
- Separate finding source ingestion from dashboard, control-plane, and
  remediation logic.
- Keep repository platform and finding source as separate axes.
- Allow file-based, API-based, and CI-artifact-based finding sources.
- Support incremental migration, starting with SonarQube wrapped behind the new
  boundary.
- Make one additional dogfooding source straightforward to add after the
  contract exists.

## 4. Non-Goals

- forcing every source through SARIF,
- replacing SonarQube immediately,
- making the first ingestion contract cover every possible external tool field,
- redesigning remediation execution around source-specific models,
- introducing a database or external service for ingestion state in this phase.

## 5. Boundary Principles

### 5.1 Platform And Finding Source Are Different Axes

These must stay separate:

- repository platform
  - GitLab
  - GitHub
- finding source
  - SonarQube
  - SARIF
  - workflow failures
  - coverage
  - tool-specific structured output

The control plane should not need to know whether a finding came from GitHub,
GitLab, Jenkins, SonarQube, Ruff, or a local artifact. It should only consume
normalized findings.

### 5.2 Normalization Happens Before Policy And Dashboard Logic

Provider-local or source-local parsing must end before:

- policy evaluation,
- dashboard item projection,
- remediation selection,
- control-plane materialization.

That means:

- source transport or artifact parsing is local,
- normalization is local,
- downstream workflow decisions are shared.

### 5.3 SARIF Is Supported, Not Mandatory

SARIF is an important ingestion path, but it is not the universal source model.

Some sources are better handled through:

- API responses, such as SonarQube
- workflow metadata, such as CI failures
- tool-native JSON, such as mypy or other non-SARIF tools

So the stable contract is not `SarifFinding`. The stable contract is the
internal normalized finding model.

## 6. Recommended Architecture

The durable shape should be:

```text
External source / artifact
  -> source-local transport
  -> source-local adapter
  -> NormalizedFinding
  -> shared policy / dashboard / remediation / control-plane
```

At the code level, the stable abstraction should be `FindingSource` or
`FindingIngestor`, not `Producer`.

Reason:

- `producer` is too broad and can mean execution, collection, parsing, or
  normalization
- the real stable seam is source-local ingestion into shared normalized
  findings

## 7. Proposed Contracts

### 7.1 Normalized Finding Domain

The internal model should be remediation- and dashboard-oriented, not
Sonar-shaped and not SARIF-shaped.

Suggested model split:

- `NormalizedFinding`
- `FindingLocation`
- `FindingSourceRef`

Suggested minimum fields for `NormalizedFinding`:

- `identity`
  - stable normalized identity used for dedupe and continuity
- `source_ref`
  - source kind
  - source item key
  - repository scope
- `title`
- `summary` or `message`
- `severity`
- `rule_id`
- `category` or `issue_type`
- `location`
  - file path
  - line
  - end line
  - optional symbol or region hint
- `source_url`
- `raw_metadata`
  - optional source-specific extension payload for later use

Suggested minimum fields for `FindingSourceRef`:

- `source_kind`
  - `sonarqube`
  - `sarif`
  - `workflow_failure`
  - later others
- `source_item_key`
- `repository_scope`

Suggested minimum fields for `FindingLocation`:

- `file_path`
- `line`
- `end_line`
- `symbol`
- `region_hint`

### 7.2 Ingestion Interface

Suggested protocol:

```python
class FindingSource(Protocol):
    def collect(self, ...) -> list[NormalizedFinding]:
        ...
```

The exact method arguments may vary by source, but the return type should stay
shared.

If transport and normalization need to stay separate, use:

- source transport
  - reads API response or artifact
- source adapter
  - converts source payload to `NormalizedFinding`

That is likely useful for SARIF because many tools can feed the same adapter.

## 8. First Implementations

### 8.1 Sonar Finding Source

The existing SonarQube path should become the first implementation behind the
new boundary:

- `SonarFindingSource`

This source may still call the current Sonar client, but it should return
normalized findings instead of pushing Sonar-specific models into downstream
services.

This is the migration anchor:

- current behavior stays intact,
- the rest of the system begins to depend on normalized findings.

### 8.2 SARIF Finding Source

The first new dogfooding source should likely be:

- `SarifFindingSource`

The first practical dogfooding tool should be Ruff because it has native SARIF
output and can run on this repository in CI.

The intended shape is:

```text
Ruff
  -> SARIF artifact
  -> SarifFindingSource
  -> NormalizedFinding
```

This gives fast dogfooding value without making the platform Ruff-specific.

Implementation boundary for the first slice:

- `SarifFindingSource` should read one or more existing SARIF artifacts from
  disk
- it should not invoke Ruff or any other analyzer itself
- analyzer execution stays in the repository pipeline or local workflow layer
- ingestion starts at the artifact boundary and ends at normalized findings

This keeps tool execution, artifact generation, and finding normalization as
separate concerns.

Additional lessons locked in after the first live Ruff SARIF dogfood pass on
Friday, July 24, 2026:

- SARIF `file://` artifact URIs that resolve inside the checked-out repository
  must be converted back to repository-relative paths instead of being
  rejected as absolute paths
- empty SARIF artifacts still need stable managed-source ownership so repeated
  sync runs can reconcile a previously populated source to zero findings
- SARIF runs with rejected, malformed, or locally unusable results must not be
  treated as authoritative for stale reconciliation
- full and partial SARIF fingerprint identities must be scoped by stable
  finding context so two distinct results cannot collapse into one dashboard
  item identity

These are now part of the expected SARIF ingestion boundary rather than follow-
up refinements.

## 9. Downstream Integration Rules

The downstream workflow should consume normalized findings only.

That means:

- dashboard sync projects normalized findings into dashboard items
- remediation selection consumes normalized findings or normalized dashboard
  items derived from them
- control-plane work-item promotion stays source-agnostic
- review projection remains independent of the original finding source

The shared workflow code should not branch on:

- SonarQube vs SARIF
- GitHub vs GitLab code scanning
- file artifact vs API transport

except at the ingestion boundary.

### 9.1 Shared Remediation Eligibility

Remediation selection must use the shared `remediation_context.category` after
dashboard projection, not `source_id` or source-local metadata.

The initial supported category is `static_analysis_fix`:

- SonarQube code-smell findings normalize to `static_analysis_fix`
- SARIF lint findings normalize to `static_analysis_fix`
- persisted dashboard items using `code_smell_fix` or `lint_fix` are normalized
  as legacy compatibility aliases at the remediation boundary
- existing SARIF fallback identities retain their `lint_fix` identity component
  so the category migration does not duplicate already-synced work items

This preserves existing dashboard work while ensuring all new supported static
analysis findings use one source-neutral eligibility contract.

Issue-class exclusions and active change-request recovery follow the same
boundary: they use the shared dashboard `rule`, `source_reference`, and file
fields for every eligible source. Source identity remains part of exclusion
identity and source-local presentation, but does not disable those safeguards.

Generated remediation branches use a canonical source-aware identity for every
source: separate source and source-reference segments include readable text and
a short digest of their raw values. This prevents collisions from punctuation,
sanitization, or ambiguous concatenation. Existing SonarQube branch names are
checked only as a lookup fallback, so already-open remediation requests remain
reusable while all new branches use the canonical form.

For GitHub rollout, one additional boundary is required:

- normalized finding intake stays shared
- GitHub publication of authoritative work-item issues stays provider-local
- repeated sync and lifecycle projection on GitHub stay provider-local at the
  transport and persistence layer while reusing shared normalized finding
  semantics

This keeps the ingestion seam honest while avoiding a false-neutral GitHub
issue transport abstraction too early.

## 10. Stable Identity Guidance

One open design challenge is stable finding identity across heterogeneous
sources.

The identity contract should be strong enough for:

- dashboard dedupe
- remediation idempotency
- cross-run continuity

Suggested first rule:

- derive identity from normalized source kind, source item key when present,
  repository scope, file path, rule id, and stable location hints

When a source has a strong external key, such as a Sonar issue key, that should
be preferred.

When a source has no strong external key, such as some SARIF records, the
identity will need to be synthesized from normalized fields.

## 11. Migration Plan

Recommended migration sequence:

### Phase 1: Introduce the boundary

- add `NormalizedFinding` models
- add `FindingSource` interface
- add `SonarFindingSource`
- keep current workflow behavior intact

### Phase 2: Move dashboard sync to normalized findings

- adapt dashboard sync to consume normalized findings instead of raw Sonar
  models
- keep remediation input shape stable where possible

### Phase 3: Add first new source

- add `SarifFindingSource`
- use Ruff SARIF as the first dogfooding source on this repository

### Phase 4: Validate source-agnostic downstream flow

- live-test dashboard intake
- publish normalized findings into authoritative GitHub work-item issues
- validate repeated GitHub sync and stale-item reconciliation
- widen remediation only after GitHub visibility and lifecycle behavior are
  trusted

## 12. Open Questions

### 12.1 Locked Decision: Minimum Normalized Finding Contract

The minimum normalized finding contract should be intentionally small and should
contain only the fields required for shared downstream selection, remediation,
projection, and operator understanding.

The minimum contract is:

- `finding_id`
- `source_id`
- `severity`
- `title`
- `summary`
- `repository_path`
- `line_start` optional
- `line_end` optional
- `region_hint` optional
- `remediation_context`

Field intent:

- `finding_id` is the stable normalized identity used by downstream workflow
  tracking
- `source_id` identifies the source instance such as SonarQube or Ruff SARIF
- `repository_path` is repository-relative
- location fields stay optional because some sources are file-level or weakly
  anchored
- `remediation_context` exists for downstream fix selection and execution, not
  for source-local trace dumping

The minimum contract should not require:

- timestamps
- artifact paths
- scan statistics
- source-specific metadata
- workflow state
- cross-source dedupe outcome

Those belong either in collection metadata or optional source extensions.

### 12.2 Locked Decision: Remediation Context Is a Small Structured Object

`remediation_context` should be a small structured object inside the normalized
finding model.

It should:

- stay provider-neutral and source-neutral
- contain only fields downstream remediation logic actually uses
- avoid becoming a loose bag of source-local properties

It may contain bounded fields such as:

- issue category or remediation type
- rule or diagnostic code when that changes remediation behavior
- narrow fixability or scope hints if downstream remediation logic consumes them

It should not contain:

- raw source payload
- renderer-only narrative text
- arbitrary tool properties
- collection-level provenance or scan statistics

### 12.3 Locked Decision: SARIF Uses a Source-Local Artifact-Paths Config Block

The first SARIF ingestion slice should use a source-local config block instead
of attaching artifact paths to review or remediation workflow settings.

The config shape should be:

```json
{
  "sarif": {
    "artifacts": [
      {
        "path": "artifacts/ruff.sarif",
        "source_id": "ruff-sarif",
        "severity_mapping": {
          "error": "high",
          "warning": "medium",
          "default": "low"
        }
      }
    ]
  }
}
```

Rules:

- the block should be named `sarif`, not `ruff`
- the field should be `artifacts`, with a path and stable `source_id` per artifact
- the ingestion source reads existing files from those paths
- the analyzer pipeline remains responsible for generating the artifacts
- each configured artifact represents one logical SARIF tool source
- an optional artifact-local `severity_mapping` maps SARIF `error`, `warning`,
  `note`, `none`, or `default` levels to shared workflow severities; absent
  mappings retain the generic SARIF mapping
- an empty artifact uses its declared `source_id` for authoritative stale-item
  reconciliation
- the declared `source_id` is the authoritative stable namespace for every
  run in the artifact; the scanner-derived tool source is retained only as
  provenance
- a configured artifact is authoritative only when all of its runs are
  complete; malformed or rejected runs prevent stale reconciliation for that
  source

Why:

- the source boundary stays format-oriented instead of tool-specific
- multiple SARIF-producing tools can later share the same ingestion adapter
- the config can grow to multiple artifacts without another shape migration
- the path does not get coupled to review or remediation concerns

### 12.3 Locked Decision: Ingestion Returns Findings Plus Collection Metadata

The ingestion boundary should return a bounded collection result, not only a
bare list of findings.

That collection result should contain:

- normalized findings
- collection metadata needed for traceability and synchronization

Typical collection metadata may include:

- source revision or scan revision
- artifact path or artifact identifier
- tool name or source label
- bounded sync statistics or warnings

This keeps the normalized finding model small while still preserving the
information needed for diagnostics, operator traceability, and later sync or
dedupe decisions.

### 12.4 Locked Decision: Source Metadata Is Optional and Explicitly Bounded

Normalized findings may support optional source-specific metadata, but that
metadata must live behind an explicit boundary rather than broadening the shared
finding contract.

The rule is:

- shared normalized finding fields are the product contract
- source-specific extras may exist in an optional `source_metadata` structure
- downstream shared workflow logic must not depend on `source_metadata` in
  Phase 6b

`source_metadata` exists for:

- traceability
- diagnostics
- detailed inspection
- future source-specific enhancements when needed

It does not exist to:

- shape the shared workflow inventory
- leak tool-local fields into remediation selection by default
- become a second unbounded remediation context

Examples of source metadata that may live behind this boundary:

- SonarQube effort or debt fields
- SARIF rule help URLs
- CodeQL query pack or query metadata
- tool-native fingerprints
- raw source categories that are not yet part of the shared contract

If a source-specific field becomes necessary for shared queueing, remediation,
or projection behavior across multiple sources, that field should be promoted
deliberately into the normalized contract rather than read ad hoc from
`source_metadata`.

### 12.5 Locked Decision: Identity Reuses Shared Overlap Matching Rules

Stable finding identity for ingestion should follow the same normalized matching
rules already used by review overlap and continuity logic, rather than inventing
a second independent identity heuristic.

The distinction is:

- overlap identity is used for matching and continuity decisions
- ingestion identity is used for persistence and downstream workflow tracking

Those are different consumers, but they should use the same shared identity
ingredients and normalization strategy.

The rule is:

- use a strong source-native finding key when one exists
- otherwise derive a fallback identity using the same matching inputs and
  normalization principles as overlap

That derived identity should be based on provider-neutral issue semantics such
as:

- repository path
- trusted line or region when available
- symbol or rule identifier when available
- normalized issue kind or category
- normalized finding title or summary semantics

When location precision is weak, the derived identity should broaden
conservatively instead of pretending to be exact.

This means:

- SonarQube-native IDs remain authoritative when present
- SARIF and other weak-key sources can still produce stable fallback identities
- ingestion, review continuity, and later dedupe logic all share one concept of
  "same underlying issue"

Implementation boundary:

- the shared identity helper should live in a neutral finding domain
- ingestion adapters may call that helper
- review overlap and continuity services may call that same helper
- the helper must not depend on review-prompt or provider-local wording

### 12.6 Locked Decision: Shared Default Queueing and Promotion Rules

In Phase 6b, all normalized findings should enter the same shared default
queueing and promotion policy after they cross the ingestion boundary.

The rule is:

- source-specific collection stays local to the ingestion adapter
- queueing, promotion, and downstream workflow behavior become source-agnostic
  by default once a finding is normalized

This means:

- SonarQube findings and Ruff SARIF findings should flow through the same
  shared promotion boundary
- the same shared severity, policy, and lifecycle rules should apply first
- source-specific queue tuning is deferred until there is explicit operator or
  product pressure to introduce it

This keeps the ingestion seam honest. If normalized findings immediately split
back into source-local queue rules, then the new shared ingestion contract is
only cosmetic.

### 12.7 Locked Decision: Shared Promotion Capacity

Promotion capacity is a shared workflow concern, not an ingestion-adapter or
provider concern. The first version applies
`remediation.max_active_work_items` to the open remediation queue on both
GitLab and GitHub. Its default is `10`; configured values must be positive
integers.

The rule is:

- collect and reconcile the full normalized finding inventory before deciding
  what to promote
- count open `approved` and `in_progress` remediation work items against the
  configured capacity
- exclude blocked, dismissed, and terminal work items from capacity while
  retaining them as visible operator records
- consider only findings already eligible under the shared workflow policy
- order eligible findings by severity, then stable finding identity
- promote only enough eligible findings to fill available capacity
- retain the remaining eligible findings as backlog-only with
  `promotion_capacity_exhausted` as their visible backlog reason

The capacity limits the durable active remediation queue rather than merely
limiting the number of new issues created by one sync. It does not change source
ownership, stale reconciliation, or lifecycle behavior for work items that
already exist. Source-specific budgets and fairness policies are deferred until
rollout data shows they are needed.

Additional v1 rules:

- lowering the configured capacity never demotes existing work; it only blocks
  new promotion until active usage falls below the limit
- an existing candidate that becomes eligible again competes for the next open
  slot using the same ordering as a newly observed finding
- stale `in_progress` work continues to consume capacity until the existing
  lifecycle or recovery flow resolves it
- capacity is repository-wide across all normalized sources
- each sync recomputes the eligible ordering, allowing newly observed
  higher-severity findings to take the next available slot

The later work-item capacity-projection slice keeps durable capacity-deferred
work closed rather than reopening it as an open `candidate`. New eligible
findings and matching closed deferred work share this same queue and ordering;
closed history does not receive a priority bonus at the same severity.

More refined sorting, source balancing, age-based fairness, and operator-set
priority are intentionally deferred until live backlog data shows they are
needed.

### 12.8 Locked Decision: Visibility Rollout Precedes Remediation Widening

After normalized finding ingestion is live on a new source, the next rollout
step should be visibility and lifecycle validation before widening remediation.

The concrete order is:

1. collect and normalize findings
2. publish promoted findings into provider-local operator surfaces
3. validate repeated sync, stale reconciliation, and operator traceability
4. only then generalize remediation eligibility for the new source

For the current rollout this means:

- GitHub work-item issue publication is the next boundary after successful Ruff
  SARIF ingestion
- the still-open remediation normalization work remains a follow-up phase,
  not part of the first GitHub visibility slice

This is a rollout rule, not a denial that the downstream workflow is shared.
The shared workflow boundary remains true; the widening order is simply staged
for safety and feedback quality.

### 12.7 Locked Decision: Cross-Source Dedupe Happens After Normalization

Cross-source dedupe precedence should not live inside source adapters in Phase
6b.

The rule order is:

- source adapters collect and normalize findings without knowing about other
  sources
- normalized findings enter the shared workflow boundary
- any cross-source dedupe or reconciliation happens later in a shared stage

This means:

- SonarQube adapters do not encode Ruff-specific precedence
- Ruff adapters do not encode SonarQube-specific precedence
- later sources such as CodeQL or workflow-failure producers can reuse the same
  shared reconciliation behavior

The shared dedupe policy should be conservative:

- if two findings are clearly the same by shared identity, keep one canonical
  work item
- preserve all contributing source provenance instead of silently discarding
  secondary source evidence
- if overlap is uncertain, do not dedupe yet

In other words, dedupe should be explicit shared reconciliation, not implicit
source-local replacement.

## 13. Recommendation

The next implementation step should be:

1. define the normalized finding domain model
2. define the shared finding ingestion interface
3. wrap the current SonarQube path behind that interface

Only after that should the first additional dogfooding source be added.

That sequence gives ZeroOne Ops a real platform boundary instead of another
source-specific producer branch.
