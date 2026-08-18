# ZeroOne Ops Dashboard Policy Acknowledgements Functional Design

> **Status: Historical.** GitLab dashboard mode is deprecated compatibility
> behavior. For current issue-mode contracts, see the [design index](../README.md).

## 1. Purpose

Define the operator-facing behavior for dashboard policy acknowledgement
replies in ZeroOne Ops.

Phase 6 introduced a dedicated dashboard policy-processing workflow. Phase 6b
should make that workflow feel responsive by replying to operator
policy comments with bounded acceptance or rejection feedback.

## 2. Goals

- give operators clear visible feedback on policy commands,
- remove the need to separately check whether a pipeline ran before knowing if
  a command was accepted,
- keep policy acknowledgements bounded, deterministic, and machine-generated,
- preserve the dashboard as the canonical policy state while adding a clearer
  interaction loop.

## 3. Non-Goals

- redesigning the `/zeroone policy` grammar,
- adding free-form conversational policy support,
- making reply notes a second authoritative policy store,
- replacing the dashboard render as the canonical visible policy result,
- solving arbitrary GitLab note-thread UX beyond dashboard policy commands.

## 4. Current Product Gap

Today an operator can leave a valid `/zeroone policy ...` command and later see
the dashboard update, but there is no acknowledgement note confirming:

- whether the command was accepted,
- whether it was rejected,
- why it was rejected,
- whether the dashboard actually changed.

That creates unnecessary uncertainty for operators, especially when the policy
job runs asynchronously.

## 5. Primary User Stories

### 5.1 Clear Feedback

As an operator, I want a reply to my dashboard policy command, so I do
not need to separately inspect pipeline execution before knowing whether the
command was understood.

### 5.2 Clear Rejection Reason

As an operator, I want malformed prefixed commands to receive a bounded
rejection reply, so I know what went wrong without guessing from unchanged
dashboard state.

### 5.3 Stable Repeated Processing

As a maintainer, I want acknowledgement replies to stay idempotent under note
replay, so rerunning policy processing does not create duplicate response
noise.

## 6. Product Model

The policy workflow should expose two operator-visible outputs:

1. canonical dashboard policy state in the dashboard body,
2. bounded acknowledgement replies attached to operator policy comments.

These outputs have different roles:

- the dashboard body remains the authoritative shared policy state,
- acknowledgement replies communicate workflow outcome for one command note.

## 7. Reply Scope

Phase 6b should acknowledge only strict prefixed dashboard policy comments.

Expected first scope:

- accepted valid policy commands,
- malformed prefixed commands that match the policy prefix but fail validation.

Out of scope:

- unrelated dashboard comments,
- free-form requests for help,
- non-policy operational discussion.

## 8. Accepted Reply Behavior

For an accepted command, the operator should receive one bounded reply that
confirms:

- the command was accepted,
- the target policy mutation that was applied,
- whether the canonical dashboard state changed.

Examples of accepted outcomes:

- accepted and changed policy,
- accepted but no effective change because the requested state already matched
  the current policy.

The reply should stay concise and machine-owned.
Accepted commands that cause no effective change should still receive a reply,
so operators do not have to guess whether the command was ignored, rejected, or
simply already satisfied.

## 9. Rejected Reply Behavior

For a malformed prefixed command, the operator should receive one bounded reply
that confirms:

- the comment was recognized as a policy command attempt,
- the command was rejected,
- the rejection reason in concise operator-facing language,
- the supported command family at a high level.

The reply should not attempt free-form coaching beyond the bounded grammar.
Phase 6b should prefer a short rejection reason plus a pointer back to the
dashboard legend or strict command forms, rather than embedding a long command
manual in every rejection reply.

## 10. Idempotency Expectations

Acknowledgements must not create duplicate reply noise when the policy runner
replays notes.

Expected product behavior:

- one operator command note should receive at most one acknowledgement reply
  from the bot for a given processing model,
- rerunning policy processing should recognize that a command note was already
  acknowledged,
- dashboard canonical state should still be recomputed from body plus note
  replay independently of whether replies already exist.

## 11. Guardrails

- acknowledgement replies are not policy authority,
- the dashboard body remains the source of truth for current policy state,
- malformed commands must not mutate policy,
- acknowledgement text should be deterministic enough for testing,
- the first version should avoid rich conversational branching.

## 12. Rollout Direction

Recommended sequence:

1. keep the current dedicated `dashboard policy` workflow as the mutation path,
2. add bounded acknowledgement replies for accepted and rejected prefixed
   commands,
3. keep reply idempotency explicit from the first implementation,
4. continue using dashboard re-render as the authoritative policy result.
