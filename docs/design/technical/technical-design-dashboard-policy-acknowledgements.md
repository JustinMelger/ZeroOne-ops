# ZeroOne Ops Dashboard Policy Acknowledgements Technical Design

## 1. Scope

This document defines the technical design for bounded acknowledgement replies
in the dashboard policy-processing workflow.

It complements
[functional-design-dashboard-policy-acknowledgements.md](../functional/functional-design-dashboard-policy-acknowledgements.md),
which defines the operator-facing behavior.

This technical design focuses on:

- acknowledgement ownership,
- reply generation and idempotency,
- interaction with the existing policy runner,
- note matching and persistence boundaries.

## 2. Architectural Direction

Acknowledgements should remain part of the dedicated dashboard policy workflow.

Recommended ownership:

- `dashboard_policy_action_service`
  - parses strict commands and classifies accepted vs rejected prefixed notes
- `dashboard_policy_processing_runner`
  - orchestrates policy replay, dashboard update, and acknowledgement handling
- a new acknowledgement-focused service
  - decides whether a note needs a reply and builds the bounded reply text

Reconciliation and remediation should not own acknowledgement behavior.

## 3. Why A Separate Acknowledgement Slice

The dedicated policy runner already isolates policy mutation from unrelated
workflows. Acknowledgements add a second operator-facing output surface, which
introduces new requirements:

- reply timing,
- reply idempotency,
- accepted vs rejected wording,
- coordination with full note replay,
- safe persistence without turning replies into authority.

That is enough new behavior to warrant its own design slice rather than being
treated as a trivial text add-on.

## 4. Proposed Service Shape

Recommended new service:

- `dashboard_policy_acknowledgement_service`

Suggested responsibilities:

1. inspect parsed policy note results,
2. decide whether one note requires a reply,
3. detect whether the note already has a bot acknowledgement,
4. build one bounded acknowledgement message,
5. return a publish plan to the policy runner.

The service should not:

- mutate canonical policy state,
- parse command grammar independently,
- decide dashboard render/update behavior.

## 5. Canonical Processing Order

Recommended policy-run order:

1. load the dashboard,
2. fetch issue notes,
3. parse policy commands,
4. replay accepted commands into canonical dashboard policy state,
5. update the dashboard body when needed,
6. compute acknowledgement replies for relevant command notes,
7. publish any missing acknowledgement replies.

This order keeps canonical policy mutation primary and acknowledgement replies
secondary.

## 6. Idempotency Strategy

Full note replay remains the policy mutation strategy, but replies need their
own duplicate-prevention rule.

Recommended first approach:

- derive a stable acknowledgement marker per operator note,
- include that marker in the bot reply body,
- when processing one operator note, scan existing issue notes for a reply from
  the bot containing that marker,
- publish a reply only when no matching acknowledgement exists yet.

This avoids introducing a separate acknowledgement cursor store.

## 7. Suggested Marker Model

The acknowledgement marker should be machine-readable but low-noise.

Recommended shape:

- include the operator note ID,
- include a stable acknowledgement kind such as `accepted` or `rejected`,
- optionally include a short workflow/version marker.

Preferred first marker format:

- a hidden HTML comment in the acknowledgement note body.

Example internal marker shape:

- `<!-- zeroone-ops:policy-ack:v1 note=12345 outcome=accepted -->`
- `<!-- zeroone-ops:policy-ack:v1 note=12346 outcome=rejected -->`

Why this format is preferred:

- easy to scan for programmatically,
- low visual noise for operators,
- stable under replay,
- leaves room for future format versioning.

## 8. Reply Publishing Behavior

Accepted reply content should be derived from parsed command intent and replay
outcome.

Recommended accepted fields:

- accepted status,
- concise description of the mutation target,
- whether canonical state changed or was already in that state.

Phase 6b decision:

- accepted commands that cause no effective policy change should still receive
  an acknowledgement note.

Rejected reply content should be derived from parser rejection details.

Recommended rejected fields:

- rejected status,
- concise rejection reason,
- short reminder to use the strict `/zeroone policy` command forms shown in the
  dashboard legend.

Phase 6b decision:

- rejection replies should stay concise and should point back to the dashboard
  legend rather than embedding a long command reference in every reply.

The runner should publish replies only for:

- accepted commands,
- malformed prefixed commands.

It should ignore unrelated comments.

## 9. GitLab Provider Boundary

Phase 6b likely requires one provider capability in addition to reading notes:

- create an acknowledgement note on the dashboard issue.

Preferred first implementation:

- publish a normal issue note that references the triggering operator note ID.

Why this is preferred first:

- easier provider/API handling than threaded reply behavior,
- clearer idempotency matching against existing acknowledgement markers,
- still easy for operators to see in the issue note stream,
- no product-model change is needed later if threaded replies are added.

Required guardrails:

- idempotency remains explicit,
- the acknowledgement is clearly tied to the triggering operator note.

Threaded reply support can remain a later transport refinement if GitLab UX
proves it is worth the extra complexity.

## 10. Failure Semantics

Acknowledgement failure should not roll back a successfully applied policy
mutation.

Recommended behavior:

- dashboard policy mutation and re-render happen first,
- acknowledgement publish failures are logged separately,
- the run summary should surface partial success or partial failure when policy
  mutation succeeded but acknowledgement publishing did not.

This prevents acknowledgement transport errors from becoming hidden policy
rollback.

## 11. Observability

The policy runner should log:

- number of accepted notes,
- number of rejected prefixed notes,
- number of acknowledgements needed,
- number of acknowledgements skipped due to existing marker,
- number of acknowledgement publish failures.

This makes acknowledgement behavior operable without turning the reply channel
into a debugging surface.

## 12. Future Extensions

Possible later additions:

- richer accepted summaries that include effective policy snapshots,
- policy-inspection replies for a future `/zeroone policy show`,
- threaded reply support if GitLab UX makes that worthwhile,
- acknowledgement batching if note volume grows.

These should remain follow-up work after the first bounded reply model lands.
