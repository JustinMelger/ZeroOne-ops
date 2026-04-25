# Functional Design: PR Review Overlap Reconciliation

## 1. Purpose

Improve repeated merge request review continuity by separating two different
jobs that the current review flow is trying to do at once:

- discover the current review findings
- decide whether those findings overlap with earlier findings on the same merge
  request

The goal is to make repeated reviews read like a continuation of the same
thread without forcing one review pass to both find issues and solve the full
history-matching problem in one step.

## 2. Problem

The current review bot is increasingly good at finding the current issue in a
new diff, but repeated review sequences still show weak continuity.

Typical failure patterns look like:

- the same concern is rediscovered with new wording instead of being treated as
  still unresolved
- a genuinely new concern is mixed into the note without being clearly marked as
  new in this pass
- an earlier concern that disappeared is not clearly acknowledged as no longer
  present

This makes repeated notes feel too pass-local and not thread-aware enough.

## 3. Goal

Split review into two bounded phases so that:

- the first phase focuses on current code review only
- the second phase focuses on overlap and continuity only
- repeated review continuity becomes stronger without weakening the trust-first
  judgment rules in the core review pass

## 4. Non-Goals

- no fully autonomous second model deciding overlap from arbitrary history with
  no app-owned candidate narrowing
- no replacement of app-owned identity or persisted review state
- no global finding identity across merge requests
- no free-form human discussion parsing in this design
- no dashboard-owned overlap logic

## 5. Primary User Story

As a maintainer reading the second, third, or fourth review on the same merge
request, I want the review to clearly distinguish:

- earlier concern still unresolved
- earlier concern no longer appears present
- new concern in this pass

so the review reads like a continuation of the same thread rather than a fresh
standalone review every time.

## 6. Functional Summary

The proposed workflow is:

1. run a normal bounded current-pass review,
2. persist or normalize the current findings,
3. build a bounded overlap packet using:
   - current findings,
   - latest prior review findings,
   - app-generated candidate matches,
4. run a second bounded overlap-reconciliation step,
5. use that result to render a more thread-aware review note.

This keeps finding discovery and overlap judgment separate.

## 7. Proposed Behavioral Split

### 7.1 Phase 1: Current-pass review

The first phase should do what the review bot already does best:

- inspect the current diff and bounded repository context
- decide whether there are current actionable findings
- return the current findings only

This phase should not carry the full burden of deciding whether a finding is
new, repeated, or resolved relative to the previous review thread.

### 7.2 Phase 2: Overlap reconciliation

The second phase should receive a bounded packet describing:

- the current findings
- the prior findings from the latest review pass on the same merge request
- app-proposed candidate overlaps based on file path, identity, symbol,
  `issue_kind`, `region_hint`, and legacy continuity fields where available

This phase should only answer a narrower question:

- which current findings overlap with earlier concerns
- which prior concerns no longer appear present in the current pass
- which current concerns are genuinely new in this pass

## 8. Trust Boundaries

### 8.1 App-owned narrowing remains required

The overlap phase should not receive the entire historical review stream and be
asked to infer everything from scratch.

Instead:

- the app should prepare a bounded candidate set
- the overlap phase should reason within that candidate set
- the app should remain the owner of final persisted state and identity

### 8.2 Review evidence still comes from the current pass

The current diff and bounded local code context remain the primary evidence.

Prior review context and overlap analysis should improve continuity, not invent
new code-backed findings.

### 8.3 Conservative fallback remains important

If overlap remains ambiguous even after candidate narrowing, the system should
prefer:

- neutral continuity wording
- under-matching
- or explicit inability to verify overlap

rather than overconfidently claiming that a concern is the same or resolved.

## 9. Candidate Generation Expectations

Before the overlap phase runs, the app should already narrow potential matches
using bounded structured information such as:

- file path
- canonical finding identity
- legacy continuity identity
- symbol
- `issue_kind`
- optional `region_hint`
- bounded title or summary similarity only as a fallback

The overlap phase should not be asked to compare every current finding against
all historical findings without this narrowing.

## 10. Output Expectations

The overlap phase should produce bounded continuity outcomes such as:

- still unresolved
- no longer appears present
- new in this pass
- overlap ambiguous

Those outcomes should then guide note rendering.

The operator-facing note should feel like:

- the earlier concern about X still appears unresolved
- the earlier concern about Y no longer appears present
- a new concern now appears around Z

rather than repeating every finding as though it were discovered for the first
time.

## 11. Why This Is Different From The Current Design

The current direction mixes:

- current bug discovery
- and historical overlap judgment

in one review pass and one prompt contract.

This proposed split treats overlap as its own bounded task.

That should improve continuity because the second step has a much smaller job:

- compare and classify,
- not discover and compare at the same time.

## 12. First Version Scope

The first version should stay conservative:

- compare only against the latest prior review pass on the same merge request
- use the current review result as-is from phase 1
- use app-generated candidate overlap sets
- keep the second phase bounded and review-owned
- preserve the existing app-owned persisted identity path
- avoid turning the second phase into a general historical reasoning engine

## 13. Success Criteria

This design is successful when:

- repeated review sequences feel more thread-aware on the same merge request
- the same concern is more often treated as still unresolved instead of being
  rediscovered from scratch
- genuinely new concerns are more clearly marked as new in this pass
- disappeared concerns are more clearly marked as no longer present when the
  current pass supports that reading
- the split does not weaken the trust-first behavior of the core review phase
