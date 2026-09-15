# Remediation Semantic Safety Technical Design

## Status

Implemented contract. This design defines the shared gate, provider projections,
and verified review-context handoff.

## Scope And Boundary

Implement a provider-neutral gate between LLM analysis and structured-edit
generation. It is mandatory in the shared remediation execution path, so GitHub
and GitLab issue mode receive identical behavior. Deprecated dashboard callers
inherit the safe execution stop but receive no new dashboard-specific UX.

The gate is not a second LLM call and does not inspect provider APIs, source
transport payloads, or raw validation output.

## Models

Add provider-neutral analysis models under `models/analysis.py`:

```python
class SemanticSafetyAssessment(BaseModel):
    current_behavior: str
    intended_behavior: str
    preservation_evidence: list[str]


class SemanticSafetyDecision(BaseModel):
    accepted: bool
    reason: str | None = None
    assessment: SemanticSafetyAssessment | None = None
```

`IssueAnalysis.semantic_safety` is required. Each text field is bounded and
non-blank; `preservation_evidence` requires at least one bounded entry. Existing
fixtures and OpenAI response contracts supply this field explicitly rather than
using a compatibility default.

Add an optional compact semantic-safety record to `WorkItemState` for the last
automated attempt. It contains accepted assessment or rejection reason, not raw
prompts, source snippets, diagnostics, or validation output. Reuse
`WorkItemExecutionFailure` for a rejected execution with `status="dismissed"`
and a new `FailureStage.SEMANTIC_SAFETY`.

## Shared Gate And Execution Flow

Add `SemanticSafetyGateService` under `services/remediation/`. It accepts an
`IssueAnalysis` and returns a pure `SemanticSafetyDecision`. It must:

1. accept `manual` without requesting an edit;
2. require all assessment fields for `auto_fixable` and `retryable`;
3. reject missing, blank, or over-bound assessment fields and evidence entries;
4. retain the accepted assessment unchanged for structured-edit prompting and
   later projection.

The gate does not assess whether the evidence is factually correct, sufficiently
specific, semantically consistent, or behavior-preserving. Existing patch scope,
validation, and review boundaries remain responsible for their respective
checks.

`AnalysisService` invokes the gate immediately after `FixGenerator.analyze()`
and before artifact patch generation or the `pre_patch_handler`. A rejected
decision returns an `AnalysisResult` with no patch and a semantic-safety
terminal-rejection stage. `ExecutionService` maps that result to the existing
`RunStatus.REJECTED` path, ensuring no branch has been created.

The existing `manual` outcome follows the same path, but retains the supplied
assessment when present. The work-item runner continues to own the provider
transition to dismissed and durable execution evidence.

## Prompt Contracts

Extend the analysis response schema and analysis prompt to require the three
semantic-safety fields. The prompt states that source diagnostics are evidence,
not authority to change behavior.

Only after an accepted decision does `AnalysisService` add the assessment to
`IssueContext` for `generate_structured_edit` as untrusted, bounded analysis
evidence. The structured-edit prompt must follow the trusted one-file and
minimal-scope constraints. It cannot supply a new classification. The execution
flow, rather than prompt text, prevents structured-edit generation after a
manual or rejected analysis.

All model-generated assessment text remains untrusted data, including when it
is sent to structured edit or displayed. The trusted execution flow controls
whether generation continues; prompt text alone is never enforcement.

## Projection And Publication

Add a deterministic **Semantic Safety** section to GitHub and GitLab change
request descriptions for gate-approved patches. It renders the three bounded
assessment fields and no raw source evidence.

GitHub and GitLab work-item renderers show the same section for semantic-safety
dismissals, adjacent to `Last Execution`. The machine-state block remains the
canonical persisted representation. Existing labels and closed-issue mapping
require no new work-item status.

## Review Context Handoff

For a published remediation change request, the review workflow loads the
persisted semantic-safety assessment through the verified work-item to
change-request link already used for review projection. It adds the assessment
to `ReviewContext` as bounded, untrusted remediation evidence; it must not
recover it from free-form change-request description text or trust identifiers
provided there.

The review prompt asks the existing review stage to compare the proposed diff
against the stated current behavior, intended behavior, and preservation
evidence. Unsupported or contradictory claims are handled as ordinary review
findings. This reuses the independent review workflow and does not add a second
LLM stage to remediation.

Review context reuses the existing bounded assessment fields and evidence
limits; it includes no raw diagnostics, code snippets, prompts, or validation
output. The prompt asks the reviewer to assess whether the diff supports the
claim, but does not require a semantic-safety finding when the review otherwise
has none.

`findings_present` retains its existing review-projection meaning when the
review identifies an unsupported claim. The planned remediation-review-feedback
flow remains responsible for any later operator requeue. Historical work items
without an assessment are reviewed normally without semantic-safety context.
The accepted assessment is persisted before publication so a failed publication
retry retains the same evidence.

Provider projection failures remain best effort and repairable by existing
status reconciliation. They do not allow structured-edit generation to resume.

## Tests

- model validation: missing, blank, oversized, and valid assessment fields;
- gate decisions: accepted local mechanical fix; manual classification; missing
  or malformed evidence; and `retryable` parity;
- analysis/execution: rejected decisions never call structured-edit, patch
  application, validation, branch creation, commit, or publication;
- prompt contracts: analysis requires the assessment and structured edit
  receives an accepted assessment only;
- rendering: GitHub and GitLab show equivalent accepted and dismissed evidence
  without raw snippets or command output;
- review handoff: a verified linked work item contributes its bounded assessment
  as untrusted review context, while description-only metadata cannot do so;
- regression: validation-feedback retries and publication retain the accepted
  assessment and do not invoke a second semantic analysis.

Run focused remediation, model, prompt, and renderer suites, then Ruff, mypy,
architecture checks, and the full test suite.

## Deferred Work

- independent semantic verification by a second model or static analyzer;
- formal behavior equivalence or test-coverage proof;
- operator requeue of semantic-safety dismissals;
- review-finding-driven revision of an open remediation pull or merge request;
- multi-file semantic assessment and repair.
