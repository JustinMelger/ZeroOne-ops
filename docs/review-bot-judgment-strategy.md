# Review Bot Judgment Strategy

## Purpose

This note captures the current trust-first review policy during the live
testing window.

The review bot still works from a bounded context packet rather than dynamic
repo exploration. Until helper-following and other context-expansion phases
land, the bot should behave conservatively when the visible code does not prove
an issue.

## Core Strategy

- prove bugs from visible code on supported paths
- when context is incomplete, make the narrowest claim the visible code
  supports
- prefer `manual_review_only` with a short explanation over speculative
  findings
- use `no_findings` only when the visible code does not justify an actionable
  issue and remaining uncertainty is limited
- explain what missing context prevents confirmation instead of implying a
  hidden unresolved concern

## Practical Rules

- do not claim confirmed breakage when the visible code only shows a possible
  inconsistency, fallback risk, or downstream compatibility question
- do not claim a contract changed unless the visible request/response contract
  shown in the review context actually changed
- treat visible schema and model inheritance as part of the contract
- do not raise findings on unsupported input paths when the visible request
  model or route contract already forbids those inputs
- when helper, caller, consumer, framework, or lifecycle behavior is missing,
  prefer a narrower claim or `manual_review_only`
- do not convert generic misuse scenarios into findings without evidence that
  the merge request introduces that misuse

## Classification Guidance

- `findings_present`
  Use only when the visible code directly supports a concrete actionable issue.
- `manual_review_only`
  Use when the code suggests something worth checking, but missing context
  prevents safe confirmation.
- `no_findings`
  Use when the visible code does not justify an actionable issue and the
  remaining uncertainty is limited.

## Why This Matters

This strategy favors trust over aggressiveness.

During the current phase, the bot should be willing to say:

- "I cannot confirm this safely from the visible context."

That is better than:

- overstating a possible issue as a confirmed bug
- returning `no_findings` while still hinting at a hidden concern

## Expected Evolution

This strategy is intentionally conservative while context is still bounded.

Later phases should let the bot make stronger claims safely by improving the
context packet, especially through:

- helper-following review context
- better prior-review reconciliation
- structured review context and reconciliation inputs

As those phases land, the bot should become more capable because it sees more
of the truth, not because it was prompted to guess more aggressively.
