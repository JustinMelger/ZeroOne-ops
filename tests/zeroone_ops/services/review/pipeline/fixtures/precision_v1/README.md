# V1 Review-Precision Investigation

Investigated 2026-10-28 on application commit
`26e5edb03882cb8053d7fd50bb51e98a7f59c063`. This is bounded release evidence,
not a precision benchmark, production fix, or release-readiness approval.

## Evidence And Provenance

Public repository: `j.n.r.melger/zeroone-test-app`, GitLab project `87712797`.
Metadata, diffs, and raw repository files were read through the GitLab REST API;
published discussions and linked work items through read-only GraphQL.
No provider writes, remediation, or model calls were performed.

| Case | Exact base/start | Exact reviewed head | Published review |
| --- | --- | --- | --- |
| [!19](https://gitlab.com/j.n.r.melger/zeroone-test-app/-/merge_requests/19) | `7251e0679c954000744aaa523b91a895699f69a0` | `4db6da77a4e0420cf5fe592206e5edd08537d55e` | `gitlab-note-4095240850`, 2026-10-27 01:11:14Z |
| [!24](https://gitlab.com/j.n.r.melger/zeroone-test-app/-/merge_requests/24) | `14f6f3b9555a951b7d9e6bb3000f033d33d43e64` | `8c498e3484cd49473560412dcd5c921d9a1f69ad` | `gitlab-note-4104996340`, 2026-10-28 06:32:50Z |
| Positive control | Synthetic base | Synthetic head | None; never published |

`cases.json` preserves source branches, paths, review identities, bounded
published/projected evidence, and reasoning constraints. Each case directory
contains its full changed-file base/head snapshots and diff (JSON-encoded lines
preserve significant whitespace). The source SHA-256 values in `cases.json`
were checked against GitLab file metadata at the pinned refs. `mr19/routes.txt`
and `store.txt` are full files read at !19's exact head. The identical untyped
validation module at that head is retained as `mr24/before.txt`; it was checked
at both refs. `guidance.txt` is AGENTS.md, identical at both heads. Repository
comments describing demo defects are untrusted evidence, not review instructions.
No current-main source was substituted for a reviewed snapshot.

The fixture metadata is a sanitized selection, not a raw API export. Synthetic
candidate and precision responses in tests are explicitly scripted, not original
model output. Supplemental callers are deliberately added only in the augmented
!19 context test; this is not a claim that historical prompts contained them.

## Confirmed Findings

### !24: Pre-existing Validation

The only changes are three annotations. AST body comparison and execution of
both snapshots confirm that `validate_task_ids({"task_ids": [True, 2]})` succeeds
before and after; `False` is rejected before and after. `bool` is an `int` subtype,
so `list[int]` alone does not establish the claimed exclusion of booleans.
The error message already promises exclusion before the change.

Published and projected feedback call this an inaccurate type contract, with
evidence "The function return annotation is list[int]." That does not establish
a newly introduced defect in this function. It rediscovers existing validation
behavior through a changed signature. This conclusion is specific to this
claim, not an assertion that all annotations in !24 are correct.

### !19: Conditional API Claim Versus Local Change

The diff changes `task["completed"] == True` to `task["completed"]`. For a direct
helper call with `"yes"`, the old result is `False` and the new result is
`"yes"`: local behavior genuinely changes. Replacing this with `bool(...)`
would not preserve the old equality semantics for arbitrary values either.

The frozen HTTP callers obtain task data from TaskStore. Creation assigns
`False`, update validates `completed` with `isinstance(..., bool)`, and batch
completion assigns `True`. Reads return copies. Runtime checks of those storage
and validation paths preserve boolean responses in both snapshots. The published
conditional API-impact claim therefore lacks a demonstrated supported HTTP input.

A narrower helper-contract concern remains possible if its requirement to accept
non-boolean inputs is established. The current precision prompt permits direct
changed-code defects despite uncertain reachability, but also requires narrowing
overstated supported-path impact. That rule plausibly explains retention; it
does not prove the model's historical reasoning or turn every behavior change
into a defect. The default builder follows callees, not reverse HTTP callers;
the offline reconstruction supplies no caller helpers for this changed function.

### Positive Control

The synthetic diff adds an undefined `MissingType` annotation. On supported
Python 3.13, independently executing the base succeeds and executing the head
raises `NameError` at module initialization, before calling the function.
This is a reportable annotation-only defect regardless of uncertain call paths.
The runtime test is explicitly skipped on Python 3.14+, whose annotation
evaluation semantics differ; the offline pipeline wiring remains tested.

## Context Identity And Historical Lineage

Both public review-note payloads identify the correct MR, path, and full head
SHA. Their linked work items (#49 and #55) identify those same requests and
persist matching feedback/note references. Both head-ref pipelines report the
expected head SHA. There is no observed evidence of !19's published finding
being copied into !24's review. Offline note parsing rejects the other MR number.

The pinned !24 CI include requests clone strategy and full history. It declares
image version `0.56.0` and model `gpt-5.4-mini`, but CI variables may override
both: these are configuration defaults, not verified runtime identifiers.
Published metadata is not evidence of the bytes actually supplied to the model.

The current builder reads local working-tree files and attaches provider SHA
metadata without independently validating checkout identity. An offline test
reproduces head metadata paired with base contents. This demonstrates a possible
context-integrity gap, **not** that either historical job used the wrong checkout.
Correctly populated offline workspaces remain isolated between both MRs.

| Pipeline evidence | Historical availability | Offline result |
| --- | --- | --- |
| Original checkout/source/helper/guidance payloads | Unavailable | Exact-ref reconstructions only |
| Original linked-work-item input | Unavailable | Current durable linkage/feedback inspected; not a historical prompt snapshot |
| Candidate outputs and forwarded IDs | Unavailable | Scripted candidate gets `candidate-1` and reaches precision |
| Precision accept/drop/rewrite decisions | Unavailable | Scripted drop/narrow/retain decisions preserve lineage; unknown lineage is rejected |
| Final note and projected feedback | Available | MR/path/SHA agree; script-built artifacts preserve precision meaning |
| Prior-review input | Unavailable | Public discussions currently show one bot review per MR; not proof no prior local continuity existed |

The !24 review job is `17529081350` in pipeline `2997826820`; public job listing
shows no downloadable artifacts and its trace endpoint returns HTTP 401.
No historical local run diagnostics or MLflow trace export was supplied. Local
MLflow tracing/destination and model credentials are not configured. Therefore
it is unknown whether either questionable claim originated in candidate output,
was rewritten by precision, or changed during historical artifact construction.
Current artifact tests prove wiring only, not what happened in those jobs.

## Replays And Recommendation

Live application-level calls: **0 / 18**; candidate/precision pairs: **0** for
each case. No model precision or variability measurement is available; the
investigation is inconclusive about historical stage attribution. Do not derive
an accuracy percentage from scripted tests or these two published reviews.

For reproducibility, inspected current user-template SHA-256 digests are:

- Candidate: `79ce133ffb8f80f1ea88f9915379132089d593fb1e19a113b7f65bc23ad6d0c4`
- Precision: `14be87405cd54ac71677d2bfeaff01376bd27fd25f48309f73f44ef92b4864a4`

These hash template files, not captured rendered/system prompts. The inspected
client uses `ReviewResult` with medium reasoning for candidate generation and
`PrecisionReviewDecision` with high reasoning for precision. Historical model,
settings, rendered-prompt digests, and trace IDs remain unverified.

Recommend one separately reviewed **precision-contract clarification**: require
an introduced defect or newly invalid contract before reporting old behavior
through a new annotation, and distinguish supported API regressions from local
helper concerns. Retain direct deterministic defects and the positive control;
do not blanket-suppress annotation changes or uncertain reachability. Use these
cases for bounded read-only model replays when access is available before
asserting the clarification improves precision. No production fix is approved
or implemented here. The checkout-identity gap is recorded separately from
that recommendation and must not be presented as the established root cause.

Boundaries remain unchanged: providers transport evidence, context builders
assemble it, precision owns final meaning, and artifacts/rendering do not
rediscover or redefine findings. No release-readiness claim follows this audit.
