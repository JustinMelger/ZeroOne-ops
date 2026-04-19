# Technical Design: GitLab-Backed Prior Review Context

## 1. Purpose

Repeated-review continuity currently depends on locally persisted review state.
That works in tests and local development, but it does not hold up in CI, where
pipeline jobs do not reliably retain `.ai-sonar-bot-state.json` between runs.

This design moves the primary continuity source to GitLab merge request review
notes, so follow-up review context can be rebuilt from the MR itself.

## 2. Problem

The current overlap-reconciliation flow expects prior review context to be
available before the review run. Today that context is primarily reconstructed
from local state.

In CI:
- jobs are effectively stateless
- prior review state is usually not present on disk
- overlap packet building returns `None`
- overlap reconciliation never runs
- the review note falls back to a fresh-pass style every time

This makes repeated-review continuity unavailable in the environment where the
bot actually runs most often.

## 3. Goals

- Rebuild prior review context directly from GitLab MR notes.
- Make MR notes the primary continuity source in CI.
- Keep prior review reconstruction strict, bounded, and bot-owned.
- Preserve MR-scoped continuity without depending on dashboard summaries.
- Allow local state to remain optional cache/supporting state, not the source of
  truth.

## 4. Non-Goals

- Parse arbitrary human discussion from the MR.
- Use dashboard content as the primary continuity source.
- Infer continuity from free-form comments.
- Reconstruct old note formats that do not expose enough bounded structure.

## 5. Source Of Truth

Primary source of truth for prior review continuity:
- bot-authored review notes on the merge request

Not the source of truth:
- dashboard summaries
- local state file alone
- free-form MR comments

This keeps continuity attached to the MR thread where the review actually
happened.

## 6. High-Level Approach

Before each review run:
1. fetch merge request notes from GitLab
2. select bot-authored review notes only
3. parse only notes that match the bot’s known review-note format
4. reconstruct prior review passes from those notes
5. use the latest prior pass whose reviewed SHA differs from the current head SHA
6. feed that reconstructed `PriorReviewContext` into the overlap packet builder

This makes prior review context portable across CI jobs without relying on local
state persistence.

## 7. Why MR Notes Instead Of Dashboard Entries

MR notes are the better source because:
- review continuity is MR-scoped
- the review note is the canonical place where findings were published
- the note contains the detailed review output, not only a mirrored summary
- dashboard content is secondary and may be summarized or transformed

The dashboard should remain an operator surface, not the reconstruction source
for repeated-review continuity.

## 8. Parsing Boundary

Only parse bot-authored review notes that contain a strict machine-safe section.

Do not parse:
- general discussion comments
- replies from developers
- free-form follow-up notes
- dashboard issue comments
- arbitrary human-readable prose as the primary continuity source

The preferred design is:
- human-readable review note for operators
- bounded machine-safe block for the bot

The bot should reconstruct prior review context from that machine-safe block, not by
relying on prose parsing as the main mechanism.

## 9. Required Structured Data In Review Notes

Each bot-authored review note should include a bounded machine-safe section that
remains stable across formatting changes in the human-readable note body.

That machine-safe block must be sufficient to reconstruct:
- review classification
- reviewed head SHA
- findings count
- per-finding summary
- optional severity
- optional structured continuity fields when present:
  - `symbol`
  - `issue_kind`
  - `region_hint`

This keeps operator-facing note wording flexible while preserving a stable
continuity source for the bot.

## 10. Reconstruction Model

Each parsed prior review note should reconstruct one `PriorReviewPass` with:
- `reviewed_head_sha`
- `classification`
- `findings_count`
- `summary`
- `note_url`
- parsed `PriorReviewFinding` entries

Each parsed prior finding should include when available:
- `identity`
- `legacy_identity`
- `summary`
- `severity`
- `symbol`
- `issue_kind`
- `region_hint`

Identity remains app-owned.

The machine-safe block may include bot-owned structured fields that help identity
reconstruction, but the app should still compute canonical identity itself during
reconstruction rather than trusting free-form prose.

## 11. Selection Rules

When multiple prior bot notes exist on the same MR:
- consider only parseable bot-authored review notes
- sort by recency
- skip notes for the current `head_sha`
- use the latest earlier reviewed pass as the overlap baseline in v1

This keeps overlap bounded to the most recent prior pass.

## 12. Service Boundary

Introduce a dedicated service, for example:
- `ReviewGitLabPriorContextService`

Responsibility:
- fetch relevant MR notes
- parse bounded bot review notes
- return reconstructed `PriorReviewContext | None`

This service should own:
- GitLab note fetching
- bot-note filtering
- strict review-note parsing
- latest-pass selection

It should not own:
- overlap matching
- note rendering
- operator feedback parsing

## 13. Runner Integration

Current runner flow:
- local state service loads prior review context

Proposed flow:
1. try rebuilding prior review context from GitLab MR notes
2. optionally fall back to local state only if needed during migration
3. inject the reconstructed context into `MergeRequestReviewContext`
4. continue into current-pass review and overlap reconciliation

After the GitLab-backed path is trusted, local-state fallback can shrink or be
removed.

## 14. Parsing Safety

The note parser should be strict and conservative.

If the machine-safe block is missing or invalid for a note:
- skip that note
- do not attempt fuzzy reconstruction from arbitrary prose as the primary fallback

If no parseable prior bot note exists:
- return `None`
- let overlap reconciliation be skipped cleanly

This keeps continuity trustworthy and explainable.

## 15. Observability

Add explicit logs for:
- whether prior MR review notes were found
- how many bot-authored notes were considered
- how many were parseable
- which reviewed SHA was selected as the prior pass
- whether no prior context was available

This will make live debugging much easier than the current silent packet-missing
behavior.

## 16. Testing Plan

### 16.1 Parser tests

Add tests for:
- parseable bot review note with findings
- parseable `no_findings` note
- parseable `manual_review_only` note
- malformed or partial note rejected
- non-bot note ignored

### 16.2 Service tests

Add tests for:
- latest prior parseable note selected
- current-head note skipped
- no parseable prior note returns `None`

### 16.3 Runner integration

Add an integration test proving:
- prior context can come from fetched MR notes
- overlap runs without local persisted review state

## 17. Migration Recommendation

Recommended rollout:
1. add GitLab-backed prior review reconstruction service
2. add parser coverage and service coverage
3. log whether runner used GitLab prior context or none
4. keep local-state fallback temporarily if helpful
5. remove local-state dependence from repeated-review continuity once the new path
   is stable in CI

## 18. Success Criteria

This design is successful when:
- repeated-review continuity works in CI without persisted local state
- overlap reconciliation runs on real follow-up MR reviews
- the runner logs clearly show whether prior context was reconstructed
- continuity depends on MR-native bot notes, not dashboard summaries

## 19. Recommendation

Adopt GitLab MR review notes as the primary continuity source, and add a bounded
machine-safe note section as the preferred reconstruction input.

That is the cleanest fit for CI, keeps review memory attached to the MR itself,
and aligns with the broader design direction of using GitLab as the operator and
workflow surface while keeping the bot’s parsing strict and bounded.
