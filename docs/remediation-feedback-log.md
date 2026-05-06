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
| 2026-05-06 | Remediation-created merge requests | Auto-created remediation PR titles should follow conventional commit style | yes | Bot-opened remediation merge requests now use a deterministic conventional-commit-style title derived from the remediation target instead of depending on ad hoc model wording | remediation logic + docs | implemented | Current format is `fix: remediate <rule-or-source-ref> in <filename>`. |
| 2026-05-06 | Remediation-created code | Generated functions should follow repo type-hint and docstring conventions | yes | Remediation prompt guidance now explicitly tells the model to follow existing repository conventions for type hints and docstrings when it introduces new helpers or functions | prompt + validation + docs | implemented | This is prompt-contract hardening first; later repo-aware validation or config support can still be added if live fixes keep drifting. |

## Pattern Notes

### Remediation PR Titles Should Follow Conventional Commit Style

- Typical shape:
  - the remediation workflow opens a merge request with a workable but
    inconsistent title
  - the title does not match the repository's expected conventional-commit
    naming style
- Preferred response:
  - implemented deterministic remediation-created MR titles around a
    conventional-commit-style pattern
  - keep the title human-review-friendly while still machine-consistent

### Generated Functions Should Match Repo Type-Hint And Docstring Conventions

- Typical shape:
  - a remediation change introduces a new helper or function
  - the generated code works, but misses repository-standard type hints,
    docstrings, or both
- Preferred response:
  - implemented clearer prompt guidance about matching repo code conventions
  - prefer repo-aware generation over generic style defaults
  - later, consider config-backed or lightweight convention-detection support
