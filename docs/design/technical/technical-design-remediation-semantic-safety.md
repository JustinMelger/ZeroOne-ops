# Remediation Semantic Safety Technical Design

## Status

Current contract. Implement after review alongside the functional semantic-safety
design.

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
`IssueAnalysis`, `RemediationExecutionTarget`, and `IssueContext` and returns a
pure `SemanticSafetyDecision`. It must:

1. accept `manual` without requesting an edit;
2. require all assessment fields for `auto_fixable` and `retryable`;
3. reject blank, over-bound, or duplicate-only preservation evidence;
4. reject evidence that declares a broader file scope than the current target;
5. retain the accepted assessment unchanged for structured-edit prompting and
   later projection.

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
`IssueContext` for `generate_structured_edit`. The structured-edit prompt may
implement only the accepted intended behavior and preserve the described
boundary. It cannot supply a new classification or alter the assessment.

All model-generated assessment text remains untrusted data when displayed. The
trusted gate controls whether generation continues; prompt text alone is never
enforcement.

## Projection And Publication

Add a deterministic **Semantic Safety** section to GitHub and GitLab change
request descriptions for gate-approved patches. It renders the three bounded
assessment fields and no raw source evidence.

GitHub and GitLab work-item renderers show the same section for semantic-safety
dismissals, adjacent to `Last Execution`. The machine-state block remains the
canonical persisted representation. Existing labels and closed-issue mapping
require no new work-item status.

Provider projection failures remain best effort and repairable by existing
status reconciliation. They do not allow structured-edit generation to resume.

## Tests

- model validation: missing, blank, oversized, and valid assessment fields;
- gate decisions: accepted local mechanical fix; manual classification; missing
  evidence; contradictory or broadened evidence; and `retryable` parity;
- analysis/execution: rejected decisions never call structured-edit, patch
  application, validation, branch creation, commit, or publication;
- prompt contracts: analysis requires the assessment and structured edit
  receives an accepted assessment only;
- rendering: GitHub and GitLab show equivalent accepted and dismissed evidence
  without raw snippets or command output;
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
