# Remediation Feedback Log

Use this log during live testing to capture concrete remediation workflow
outcomes, group them by remediation-quality pattern, and decide whether the
right response is prompt guidance, validation, remediation logic, operator
handoff, or documentation.

## How To Use

For each notable remediation outcome, add one row with:

- the dashboard item, merge request, or run reference
- whether the outcome itself was correct
- the main remediation pattern
- a short note about why
- the chosen action

Suggested action values:

- `docs`
- `prompt`
- `validation`
- `remediation logic`
- `operator handoff`
- `observability`
- `no change`

Suggested status values:

- `new`
- `tracking`
- `patched`
- `implemented`
- `validated`
- `closed`

## Log

| Date | Item / Run | Pattern | Valid? | Assessment | Action | Status | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-05-06 | Remediation-created merge requests | Auto-created remediation PR titles should follow conventional commit style | yes | Bot-opened remediation merge requests should use clearer standardized titles so human reviewers can scan intent and change type quickly | remediation logic + docs | tracking | Prefer conventional-commit-shaped MR titles instead of ad hoc summaries when the bot opens remediation changes. |
| 2026-05-06 | Remediation-created code | Generated functions should follow repo type-hint and docstring conventions | yes | When remediation introduces new functions, the generated code should match repository standards for type hints and docstrings instead of leaving style mismatches for humans to clean up | prompt + validation + docs | tracking | This should likely be driven by prompt guidance plus validation against existing repo conventions or explicit config. |

## Pattern Notes

### Remediation PR Titles Should Follow Conventional Commit Style

- Typical shape:
  - the remediation workflow opens a merge request with a workable but
    inconsistent title
  - the title does not match the repository's expected conventional-commit
    naming style
- Preferred response:
  - standardize remediation-created MR titles around a configurable or
    repository-aligned conventional-commit pattern
  - keep the title human-review-friendly while still machine-consistent

### Generated Functions Should Match Repo Type-Hint And Docstring Conventions

- Typical shape:
  - a remediation change introduces a new helper or function
  - the generated code works, but misses repository-standard type hints,
    docstrings, or both
- Preferred response:
  - make prompt guidance and validation more explicit about matching repo code
    conventions
  - prefer repo-aware generation over generic style defaults
  - later, consider config-backed or lightweight convention-detection support
