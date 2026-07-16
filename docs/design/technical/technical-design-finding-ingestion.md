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
- live-test remediation selection
- live-test GitHub control-plane work-item projection using the new source

## 12. Open Questions

- What is the minimum normalized finding contract required for remediation
  selection and execution?
- Should normalized findings support optional source-specific extension
  metadata, and if so where?
- Where should dedupe precedence live if multiple sources report the same
  underlying problem?
- Should ingestion return only findings, or findings plus collection metadata
  such as source revision, artifact path, or sync statistics?
- How strict should stable identity be for sources without strong external
  finding keys?

## 13. Recommendation

The next implementation step should be:

1. define the normalized finding domain model
2. define the shared finding ingestion interface
3. wrap the current SonarQube path behind that interface

Only after that should the first additional dogfooding source be added.

That sequence gives ZeroOne Ops a real platform boundary instead of another
source-specific producer branch.
