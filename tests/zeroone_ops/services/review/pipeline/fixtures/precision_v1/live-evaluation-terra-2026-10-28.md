# Production-Model Replay: Terra, 2026-10-28

## Outcome

`gpt-5.6-terra`, identified by the operator as the production model, completed
the same three-case evaluation with exactly 18 application-level calls. The
known !24 boolean-ID false positive was absent from all final reviews, !19
produced no unsupported API-regression claims, and the annotation import failure
remained reportable in all three repetitions.

These bounded case expectations were met. Operator acceptance before v1 remains
separate; this is not proof of general accuracy or deterministic behavior.

| Case | Repetition | Candidate findings | Final precision outcome | Calls |
| --- | --- | --- | --- | --- |
| !24 | 1 | None | `no_findings` | 1-2 |
| !19 | 1 | None | `no_findings` | 3-4 |
| Annotation control | 1 | Undefined annotation | Retained, high severity | 5-6 |
| !24 | 2 | Optional pagination type mismatch | Retained, medium severity | 7-8 |
| !19 | 2 | None | `no_findings` | 9-10 |
| Annotation control | 2 | Undefined annotation | Retained, high severity | 11-12 |
| !24 | 3 | Pagination mismatch and boolean-ID claim | Pagination retained, low severity; boolean claim dropped | 13-14 |
| !19 | 3 | None | `no_findings` | 15-16 |
| Annotation control | 3 | Undefined annotation | Retained, high severity | 17-18 |

All nine artifacts passed structural validation. Findings varied between
repetitions: !24's pagination issue was found twice, not every time, and its
severity varied. Passing the targeted checks does not mean identical outputs.

## Observed Lineage And Independent Checks

In !24 repetition 3, candidate generation emitted the old boolean-ID concern as
`candidate-2`. Precision dropped it as `unsupported_scope`, explaining both that
the behavior predates the diff and that Python typing treats `bool` as an `int`
subtype. No boolean-ID concern survived in repetitions 1 or 2 either.

The separate pagination concern was introduced by candidate generation and
retained by precision in repetitions 2 and 3, preserving `candidate-1` lineage.
The changed signature declares `dict[str, str | None]`, but `offset` and `limit`
are passed to `int()` without narrowing a present `None` value. A `get` default
does not replace an existing `None` entry.

A local MyPy check of the exact `parse_query` function from the frozen head
reported two `arg-type` errors for `int(str | None)`. Independent execution of
the frozen base and head raises `TypeError` for both `{"offset": None}` and
`{"limit": None}`. Thus the runtime behavior already existed, but the new
annotation declares a contract incompatible with the typed body. This supports
a local type-contract finding, not a demonstrated new HTTP regression. No
remote code or demo MR was changed to verify it.

!19 candidate generation and precision consistently used the supplied caller,
storage, and validation evidence to preserve the supported boolean response
contract. The synthetic positive control was consistently retained with
`candidate-1` lineage and high severity. Its import-time behavior is assessed
against the fixture's Python 3.13 requirement.

## Controlled Comparison And Provenance

The [Luna evaluation](live-evaluation-2026-10-28.md) remains unchanged. Its known
boolean-ID false positive survived precision once; no such finding survived
this Terra replay. This is an observed difference on these cases, not a
statistical model ranking or evidence that either model is universally better.

- Window: 2026-10-28 19:41:01-19:43:09 UTC.
- Configured and returned model identifier: `gpt-5.6-terra`.
- Application base: `080d521`, plus the same uncommitted prompt clarification
  used for Luna. No prompt or service changes were made between the runs.
- The same temporary replay script invoked the real candidate and precision
  services, then artifact construction and structural validation. It supplied
  no expected answers or scripted responses and invoked no extra model stages.
- Review configuration, SDK retry settings, tracing setting, template hashes,
  context hashes, and candidate system/user message hashes were compared from
  both local journals and were identical. Only the configured model differed;
  precision messages naturally varied with real candidate output.
- Candidate schema/reasoning: `ReviewResult`, medium. Precision schema/reasoning:
  `PrecisionReviewDecision`, high. SDK retries remained 2; no application-level
  API errors occurred. The budget counts application calls, not independently
  measured HTTP retries.
- The fixed settings, pinned source identities, reconstructed helper/guidance
  inputs, and context/candidate-input digests are recorded in the Luna report.
  In particular, !19 includes supplemental callers; neither replay proves which
  source or caller evidence reached the historical CI review.
- No original descriptions, verified work-item context, or prior passes were
  supplied. This does not recover historical stage attribution.
- MLflow was disabled. Response/request references remain in the local temporary
  journal only, outside tracked fixtures. No credentials or raw operational
  exports are included here.
- API-reported usage: 65,037 input tokens, 8,414 output tokens, 73,451 total.
  No monetary cost or comparative performance claim is inferred.
- This run used its own operator-requested 18-call budget, separate from Luna's
  exhausted 18-call run. No further calls were made after completion.
- No GitHub/GitLab reads or writes, remediation, release tags, or repository
  source edits occurred during the evaluation.

Template SHA-256:

- Candidate: `5d242d24542c9516b8b353134564db3da4e06613fdefd6650c32c0a1c02216f3`
- Precision: `c4a7ec220dba5f87493331415964fa577d1d57fa952c901d1f2da35a2afa2893`

Precision system/user input digests:

| Call | SHA-256 |
| --- | --- |
| 2 | `56025aac8b591e4764d0d2added1dbebd7e10ec57f0ed2e8673d3c930e0353c5` |
| 4 | `2ee2d9ed980673f7544259d42f5c1d7ada2b680c39e569a04c134983b9163f3e` |
| 6 | `3a3539975371874c0ba855c4fc36e5eb467144e8bfb51105eda0ff1dc1b78670` |
| 8 | `5ec7541e4410630bf3686fae479581c78443d3200c9e1d02b48fe6111188d6a2` |
| 10 | `cc0e4e47c043aa96ce8cd8afc18cc1f4d97aa6142a35d8446ca90ec88b5df592` |
| 12 | `b0a6c064873c897756e25cf932d879d57e5f2d3fad5e158ad883d386faffecbc` |
| 14 | `38611f42e8bef44459af6fb262fd5c25c2a522973a27c6c9bc2943a15f25d45e` |
| 16 | `fcd4fd2c948611b347400340d4a26be8128b45468631a297898096f81d1daf50` |
| 18 | `50a54b29a1f2f55ad7b5fc33dc5250e040dfa0fdaee7467d8cde5c33bfa0fbc9` |

## Acceptance Boundary

The production-model replay supports keeping the general clarification without
adding a Python-specific suppression rule or another model stage. Preserve both
model reports and obtain operator acceptance of these model-specific results
before closing the review-precision gate. Other provider rollout and v1 release
gates are unaffected.
