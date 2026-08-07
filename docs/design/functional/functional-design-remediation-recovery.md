# Remediation Recovery Functional Design

## 1. Purpose

Define one operator-controlled recovery flow for remediation work that becomes
blocked after a failed execution, failed publication, or closed-unmerged change
request.

Recovery must work with GitLab dashboard items and GitHub work-item issues
without making either provider's storage model the shared product contract.

## 2. Goals

- keep automatic remediation conservative: blocked work never retries itself;
- give authorized operators a small, explicit set of recovery choices;
- preserve the prior branch, change-request, execution, and review traceability;
- distinguish retrying a known-safe publication from starting new code work;
- keep the same recovery semantics on GitLab and GitHub.

## 3. Non-Goals

- automatically reopening a closed merge request or pull request;
- automatically retrying validation, code generation, or publication;
- allowing arbitrary free-form changes to persisted work-item state;
- solving concurrent claim ownership in this phase;
- adding multi-file remediation or test repair.

## 4. Recovery Model

Recovery is available only for a blocked remediation item. An authorized
operator chooses exactly one action:

| Action | Meaning | Result |
|---|---|---|
| `dismiss` | Do not automate this item further. | The item becomes `dismissed`; history remains visible. |
| `retry` | Ask ZeroOne Ops to recover the item through the safest available path. | The backend either retries a verified publication or starts a new attempt. |

For `retry`, the backend chooses one of two internal recovery plans:

- `retry-publication`: reuse a verified branch and commit after only a
  change-request publication failure;
- `start-fresh`: preserve the old attempt and return the item to the eligible
  queue with a new attempt identity.

This keeps the operator experience simple without making branch reuse unsafe.

## 5. Safety Rules

The recovery service must enforce these rules before changing state:

1. The item is a remediation item and is currently `blocked`.
2. Current policy permits automation, except that `dismiss` remains available.
3. The requested action is valid for the recorded failure state.
4. A closed-unmerged change request is never reopened or reused automatically.
5. A fresh attempt receives a new attempt identity and a new branch name. It
   must not overwrite the old branch or change request.
6. Every accepted action records the actor, timestamp, request reference,
   previous status, resulting status, and concise reason.
7. `dismiss` creates a durable suppression record for the same stable finding
   identity. A later source sync must not recreate the item while that record
   exists.

If an item changed after the operator wrote a command, the request is rejected
as stale rather than applied to newer state.

## 6. Operator Experience

Recovery actions use provider-native comments and the existing authorization
boundary:

- GitLab: a Maintainer or Owner comments on the dashboard issue and identifies
  the dashboard item.
- GitHub: a repository admin comments on the authoritative work-item issue;
  the issue itself identifies the item.

Command scope is intentionally separate:

- repository-wide policy commands are accepted only on the policy overview
  surface: the dedicated GitHub policy issue or the current GitLab dashboard
  issue;
- recovery commands are accepted only on the affected remediation work item:
  the GitHub work-item issue, or the GitLab dashboard item identified in a
  dashboard note.

An otherwise valid command on the wrong surface is not applied.

Recommended v1 commands:

```text
# GitLab dashboard issue
/zeroone remediation <item-id> dismiss
/zeroone remediation <item-id> retry

# GitHub work-item issue
/zeroone remediation dismiss
/zeroone remediation retry
```

The command processor records the requested authoritative state transition and
returns the item to `approved`. The normal remediation runner is the only
execution owner: it claims the item, performs the selected retry or fresh
attempt, and records the resulting lifecycle state. Command processing must not
generate a patch, validate code, push a branch, or publish a change request.
The initial version does not need conversational acknowledgement replies;
operators can inspect the rendered item and workflow run.

When an item is blocked, its rendered view must include:

- the concise failure or reconciliation reason;
- the latest execution or publication link when available;
- the provider-appropriate `retry` command;
- the provider-appropriate `dismiss` command.

For example, a GitHub work-item issue can show:

```text
Recovery: This remediation is blocked because validation failed.
Retry safely: /zeroone remediation retry
Stop automation: /zeroone remediation dismiss
```

GitLab renders the equivalent commands with the dashboard item ID. These
instructions appear only for blocked remediation items.

## 7. State And Traceability

Recovery adds an append-only, bounded attempt history to the shared work-item
concept. Each entry captures:

- action and reason;
- actor and provider comment reference;
- time of the decision;
- prior and resulting lifecycle status;
- prior branch and change-request references when present;
- the new attempt number for `start-fresh`.

The latest active branch and change request remain the primary fields used by
automation. History is for operator audit and must not drive automatic retry.
Retain the most recent ten events in provider-managed state.

## 8. Provider Mapping

| Shared concept | GitLab | GitHub |
|---|---|---|
| Authoritative work state | Dashboard item | Work-item issue |
| Recovery command surface | Dashboard issue note | Work-item issue comment |
| Authorization | Maintainer or Owner | Repository admin |
| Rendered recovery state | Dashboard row and machine state | Issue body and machine state |
| Fresh-attempt branch | New bounded attempt suffix | New bounded attempt suffix |

The GitHub operational summary remains read-only and links to work items. It is
not a policy or recovery command surface.

## 9. Outcome Rules

- `dismiss`: terminal for automatic pickup. A later source sync must preserve
  it until an operator deliberately restores the item or a distinct finding
  identity is discovered.
- `completed` with resolution `no_change_required`: normal remediation analysis
  proves that the current workspace no longer needs a change for the selected
  target. The item is not dismissed and is not awaiting operator action.
- `retry`: choose `retry-publication` only when the branch and commit still
  match. The command queues the item as `approved`; the regular remediation
  runner claims it, verifies the branch, and then links a newly created or
  reused open change request. Otherwise choose `start-fresh`: retain prior
  traceability, clear active execution-only state, increment the attempt
  number, and return to `approved` when eligible. The regular remediation
  runner then claims it normally.
- A fresh retry returns the item to the normal remediation runner without
  invoking source sync. If that runner proves from the current workspace that
  no change is required, it transitions the item to `completed` with resolution
  `no_change_required`. A verified publication-only retry remains narrower
  because it does not create new code.

## 10. Acceptance Criteria

- An unauthorized command cannot change recovery state on either provider.
- A blocked item can be dismissed without losing prior traceability.
- A dismissed finding remains suppressed across later source-sync runs.
- A target that no longer needs a local code change becomes completed with
  `no_change_required`, rather than dismissed or blocked.
- A recorded failed publication can be retried without rerunning the LLM,
  patch, or validation stages.
- A fresh attempt cannot reuse or force-push the prior attempt branch.
- Closed-unmerged change requests remain blocked until an explicit action.
- A fresh remediation run can complete an item as `no_change_required` only
  from bounded current-workspace evidence, not from a missing source artifact.
- Stale commands and invalid action/state combinations are visible in logs and
  leave authoritative state unchanged.
