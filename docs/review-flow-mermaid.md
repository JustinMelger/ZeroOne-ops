# Review Flow Diagram

This diagram reflects the current implemented staged review flow.

It is intended as a quick reference for:

- current stage boundaries
- LLM-assisted stages vs app-owned stages
- where continuity, validation, and fallback happen

```mermaid
flowchart TD
    A[MR Intake] --> A1{Authoritative same-SHA review exists?}
    A1 -->|yes| A2[App-owned reuse response]
    A2 --> A3[Persist run record only]
    A3 --> U[Operator-visible dashboard state]
    A1 -->|no| B[Review Context Builder]

    B --> C[Candidate Generation Stage]
    C --> C1[LLM candidate prompt]
    C1 --> C2[Raw structured review result]
    C2 --> C3[Candidate artifact]

    C3 --> G[Grounding checks]
    G --> G1[Accepted grounded candidates]
    G --> G2[Dropped grounding candidates]

    B --> H[Bounded prior-review context]
    G1 --> I[App-owned overlap hints]
    H --> I

    G1 --> J[Precision / Reconciliation Stage]
    H --> J
    I --> J
    B --> J

    J --> J1[LLM precision prompt]
    J1 --> J2[Precision decision]
    J2 --> J3[Normalization]
    J3 --> J4[Exact candidate accounting]
    J3 --> J5[Deterministic retained-finding ordering]
    J4 --> K[ReconciledReviewDecision]
    J5 --> K
    G2 --> K

    K --> L[Overlap Reconciliation Stage]
    L --> L1[LLM overlap prompt]
    L1 --> L2[Overlap outcomes]
    L2 --> M[Attach continuity outcomes]
    K --> M

    M --> N[Artifact Builder]
    N --> N1[PublishableReviewArtifact]

    N1 --> O[Artifact Validator]
    O -->|valid| P[Publish normal artifact]
    O -->|rejected| Q[Manual review only fallback]

    P --> R[Persist Review State]
    P --> S[Dashboard Mirror]
    Q --> R
    Q --> S

    R --> T[Future prior-review context]
    S --> U[Operator-visible dashboard state]
```

## Notes

- `candidate generation`, `precision / reconciliation`, and `overlap reconciliation`
  are the current LLM-assisted stages.
- `grounding`, `normalization`, `artifact building`, `validation`, `state persistence`,
  and `dashboard mirroring` are app-owned.
- Same-SHA reuse is an app-owned operational early exit, not a new review pass.
- The precision stage owns final review meaning.
- The validator owns publish safety, not review truth.
- Repair is intentionally not implemented yet; current validator fallback is
  `manual_review_only`.
