# Bounded Live Review Evaluation: 2026-10-28

## Outcome

**Acceptance remains open.** Three repetitions of the three frozen cases used
exactly 18 application-level model calls. !19 and the positive control met their
case expectations, but !24's known boolean-ID false positive survived precision
in one repetition. No prompts were changed during the run and no further calls
were made after reaching the cap. This small sample is not an accuracy estimate.

| Case | Repetition | Candidate findings | Final precision outcome | Model calls |
| --- | --- | --- | --- | --- |
| !24 | 1 | Boolean-ID claim | Dropped as `unsupported_scope`; `no_findings` | 1-2 |
| !19 | 1 | None | `no_findings` | 3-4 |
| Annotation control | 1 | Undefined annotation | Retained, high severity | 5-6 |
| !24 | 2 | Boolean-ID claim and input-annotation concern | Both retained; `findings_present` | 7-8 |
| !19 | 2 | None | `no_findings` | 9-10 |
| Annotation control | 2 | Undefined annotation | Retained, high severity | 11-12 |
| !24 | 3 | None | `no_findings` | 13-14 |
| !19 | 3 | None | `no_findings` | 15-16 |
| Annotation control | 3 | Undefined annotation | Retained, high severity | 17-18 |

All nine final artifacts passed structural validation. That does not establish
semantic correctness: the erroneous !24 finding also produced a valid artifact.

## Observed Lineage And Interpretation

For !24 repetition 1, candidate generation introduced the claim that returning
booleans violates `list[int]`. Precision correctly noted that the behavior
predates the annotations and that Python's `bool` is a subtype of `int`.

Repetition 2 introduced the same claim in `candidate-1`; precision retained it
as "Unsound integer-only return annotation" at medium severity. The retained
impact claims that an integer-only result excludes booleans, which the language
type relationship does not establish. The final artifact preserved the precision
decision rather than creating this claim itself. In repetition 3, candidate
generation returned no findings and precision preserved that outcome.

An independent local MyPy check accepted `def ids() -> list[int]: return [True, 2]`.
The offline frozen-source tests also establish that `True` was accepted before
and after !24 while `False` was rejected by the positivity check. No type-error
evidence supports the retained integer-only claim.

Repetition 2 also retained `candidate-2`, "Input annotation omits validated raw
values", concerning `validate_body(body: dict[str, object])`. The supplied !24
context does not demonstrate a typed caller failure for malformed inputs; this
separate contract concern needs assessment against actual callers. The known
boolean-ID error is sufficient to withhold acceptance without pre-labeling
every other concern invalid.

For !19, both stages consistently used the supplied storage, route, and
validation evidence to conclude that supported completion values are booleans.
For the positive control, both stages consistently retained the undefined
annotation's import-time `NameError`, with `candidate-1` lineage intact.
The positive control is assessed against Python 3.13, not later annotation
evaluation semantics.

These are observed stages for this replay only. They do not resolve historical
stage attribution for the original demo reviews, nor establish improvement
against the old prompts or a different model.

## Settings And Provenance

- Window: 2026-10-28 19:21:52-19:24:31 UTC.
- Configured and returned model identifier: `gpt-5.6-luna`.
- Application base: `080d521`, with the working-tree clarification identified by
  the template hashes below. No other production behavior was changed.
- Real `ReviewCandidateGenerationService` and `ReviewReconciliationService`
  calls used the existing OpenAI client, followed by artifact building and
  structural validation. No expected answers or scripted model responses were
  supplied. No extra model stages were invoked.
- Candidate schema: `ReviewResult`, medium reasoning. Precision schema:
  `PrecisionReviewDecision`, high reasoning. Normal SDK retry setting: 2;
  no application-level API errors occurred. The cap counts application calls,
  not an independently instrumented count of underlying HTTP retries.
- Review limits: 5 changed files, 3 findings, 2 prior passes; context 400 lines
  before/after, function context 200 lines, helper depth 1, 3 helpers per function,
  120 lines per helper and 240 per review. Inline comments disabled; supported
  paths `src/` and `tests/`, no ignored paths. Only bounded frozen source was used.
- !24 used its exact frozen head file and AGENTS.md. !19 additionally received
  frozen routes, storage, and validation files as reconstructed helper evidence.
  This is augmented context, not proof the original job had those callers.
- No original descriptions, verified work-item context, or prior-review passes
  were supplied. Those historical model inputs remain unavailable. The cases
  retain the pinned MR/base/head identity in the [original report](README.md).
- MLflow was disabled. Per-call response/request references and usage were
  retained only in the local temporary journal, not in tracked fixtures.
- Usage reported by the API: 65,091 input and 12,966 output tokens, including
  caching/reasoning as reported; 78,057 total. No monetary estimate is inferred.
- No GitHub/GitLab reads or writes, remediation, source edits, release tags, or
  credentials were included in model context or tracked results.

Template SHA-256:

- Candidate: `5d242d24542c9516b8b353134564db3da4e06613fdefd6650c32c0a1c02216f3`
- Precision: `c4a7ec220dba5f87493331415964fa577d1d57fa952c901d1f2da35a2afa2893`

The candidate request-input digest was stable across repetitions for each case:

| Case | Context SHA-256 | Candidate input SHA-256 |
| --- | --- | --- |
| !24 | `160ef6685defc533f41a9952eadb6183fae84b839eb02cfdd31617778d71ab70` | `d404b8b62e1e68db170d3728e477c9ec128d339d7c040411fa0400eed42825f2` |
| !19 | `c3c35c9703440e1b159d22849f7cbca76acea0d1802e410beae70dee707de10d` | `619e1b8e0a7954deed06135ae8df5905326591b51f228664dcee74c5df9d26f8` |
| Annotation control | `4222b0abcd6c0c472cfbd88b297d7afb3ce7a21334ed92fbc271784b2dd10ab3` | `3299f5475dcb692885387cc89348d00803be6ad63775b1505362f9742b529939` |

Context hashes cover JSON-mode context models; request-input hashes cover the
serialized system/user messages passed to the SDK. Precision inputs vary with
the preceding real candidate output:

| Call | Precision input SHA-256 |
| --- | --- |
| 2 | `54ad049a815c0160dc53527ae733cc1dfa584e6cc621e15bdead85372a33049b` |
| 4 | `b6e474b96ad27a2163df2785f8faca60e807654195c27bae6ddcce6653f28b6a` |
| 6 | `28151c5ef3f3004cd564ad88a37ebc5f5fedb34ef5835f95110b0d29b12dec2e` |
| 8 | `8770bea6b9ba61e2461c49239714df0e2c0b55731dc4a0162deda452ac9ece97` |
| 10 | `239961ed9732a4326a981299fa4685cc3b2899063e37b52569e51a8620d07d65` |
| 12 | `9c4bb9992c88f38188010b23910087158c26a3ab1c3e027bb65014babdd2c674` |
| 14 | `a72fd30249212ede269d2c3b90b59163309c880d60946dd8c08348d906b5510d` |
| 16 | `aeb81d7d1900b5db2c3a1172b9870a4fcc96ff7c77c4b6d15b84808220438554` |
| 18 | `d15710276eb86460e4f87e63666f2eafff2179ee721b1c695fd9a1300b10ce0b` |

## Follow-up

Keep the review-precision release gate open. Review the surviving subtype
misinterpretation before deciding on another prompt change or an alternative
model. Any further live evaluation needs a separately agreed budget; this run
is complete at 18 calls. The result does not justify deterministic suppression
of annotation findings, a new model stage, or a claim of release readiness.
