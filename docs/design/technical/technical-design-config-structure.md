# ZeroOne Ops Config Structure Technical Design

## 1. Scope

This document defines the near-term configuration direction before remediation
is rolled out to additional live repositories.

The goal is to stabilize the operator-facing config contract now, before more
repos adopt remediation and before multiple source producers make the current
flat config harder to evolve safely.

This is a rollout-shaping design slice, not a full platform redesign.

## 2. Why Now

Review is already live in multiple repositories.

Remediation has so far been exercised mainly in a test repository. Once
remediation is rolled out to more live repos, config shape becomes part of the
product contract:

- operators will copy and maintain these configs across repos
- example configs and runbooks become upgrade surfaces
- later config migrations will cost more once several repos depend on them

So the right time to settle the structure is before the broader remediation
rollout, not after it.

## 3. Design Goals

- make config ownership clearer by workflow and source
- keep operator-facing config understandable for review-only repos and
  remediation repos
- reduce mixed top-level policy fields
- preserve compatibility during migration
- make room for additional remediation producers later

## 4. Current Problems

The current config is mostly flat:

- shared runtime settings
- remediation policy
- review policy
- source-specific behavior

all live close together at the top level.

That creates a few problems:

- ownership is unclear
  - for example remediation-specific policy can look like global app policy
- rollout is harder to explain
  - review-only repos still see remediation-oriented fields
- future producers will worsen the flatness
  - `pipeline_failure`, `security_scan`, and later sources will need their own
    source-specific settings

## 5. Target Direction

The long-term operator-facing config should be organized around:

- shared runtime/app settings
- workflow blocks
- source blocks

Recommended top-level shape:

- `execution_mode`
- `base_branch`
- `branch_prefix`
- `dry_run`
- `state`
- `gitlab`
- `review`
- `remediation`
- `sonarqube`

Later:

- `pipeline_failure`
- `security_scan`

## 6. Proposed Responsibility Split

### Shared top-level runtime settings

Keep only settings here that are truly cross-cutting:

- execution mode
- base branch
- branch prefix
- dry-run defaults
- state path
- GitLab MR publishing defaults

### `review`

Keep review-specific behavior here:

- file/context limits
- helper-following controls
- draft-MR handling
- prior-review retry/feedback limits
- supported/ignored review paths

### `remediation`

Move remediation-specific behavior here:

- coarse severity intake policy
- remediation retry limits
- future remediation policy toggles
- future dashboard policy controls when they become real product surface

### `sonarqube`

Keep source-specific remediation intake behavior here:

- mock issue fixture path
- future source-specific intake options if needed

Connection secrets still remain environment-driven for now:

- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`

## 7. Recommended First Stable Rollout Shape

We do not need to move every field at once.

The first stable rollout shape should focus on the fields that matter most for
live repo adoption:

### Keep at top level for now

- `execution_mode`
- `base_branch`
- `branch_prefix`
- `dry_run`
- `apply_patch_in_dry_run`
- `write_solution_artifacts_in_ci`
- `openai_solution_output_path`
- `validation_commands`
- `gitlab`
- `state`
- `analysis`
- `approval`

### Keep in `review`

- all current review settings already live there and should stay there

### Add or strengthen `remediation`

Recommended first fields:

- `bootstrap_severities`
- `max_retry_count`
- `analysis`

### Add or strengthen `sonarqube`

Recommended first fields:

- `mock_issues_path`

This is enough to give the config a clearer product shape without forcing a
large migration all at once.

## 8. Policy Direction

The intended remediation policy model should be:

- config gives coarse rollout control
- hard safety guards stay in code
- operator exclusions narrow automation further

That means:

- config should use severity as the coarse inclusion knob
- config should not return to detailed rule allowlists
- rename-style and similar hard safety boundaries should remain built-in code
  policy, not operator config

## 9. Compatibility Strategy

This migration should be compatibility-first.

Recommended approach:

1. support the new nested shape in config loading
2. keep reading the legacy flat keys during migration
3. prefer new nested values when both are present
4. update shipped examples and runbook to the new structure
5. remove legacy keys only after remediation has been live in real repos long
   enough to justify cleanup

Why:

- review is already live in multiple repos
- remediation rollout should not require a flag-day migration
- example configs should guide new repos toward the new shape while old repos
  continue working

## 10. Example Target Shape

```json
{
  "execution_mode": "ci",
  "base_branch": "main",
  "branch_prefix": "zeroone-ops",
  "dry_run": false,
  "validation_commands": [
    "uv run pytest",
    "uv run mypy src",
    "uv run ruff check ."
  ],
  "gitlab": {
    "target_branch": "main",
    "labels": ["zeroone-ops", "sonarqube"]
  },
  "state": {
    "path": ".zeroone-ops-state.json"
  },
  "review": {
    "max_changed_files": 5,
    "max_findings_per_review": 3,
    "max_prior_review_passes": 2,
    "max_context_lines_before": 30,
    "max_context_lines_after": 30,
    "supported_paths": ["src/", "app/"],
    "ignored_paths": ["src/generated/"],
    "skip_draft_merge_requests": true,
    "max_review_feedback_retries": 1
  },
  "remediation": {
    "bootstrap_severities": ["LOW", "MEDIUM", "HIGH"],
    "max_retry_count": 1,
    "analysis": {
      "context_lines_before": 40,
      "context_lines_after": 40,
      "max_file_bytes": 200000
    }
  },
  "sonarqube": {
    "mock_issues_path": "fixtures/sonar/issues.json"
  }
}
```

## 11. Implementation Phases

### Phase 1: Loader Compatibility

- add nested `remediation` and `sonarqube` config models
- teach settings loading to accept both old flat keys and new nested keys
- prefer nested keys when both are present

### Phase 2: Internal Usage Cleanup

- update internal call sites to read remediation policy from
  `config.remediation`
- update Sonar fixture usage to read from `config.sonarqube`

### Phase 3: Operator Surface Update

- update `.zeroone-ops.json`
- update example configs
- update runbook
- keep fallback for legacy live repos

### Phase 4: Post-Rollout Cleanup

- once remediation has been live across repos long enough, decide whether to
  remove legacy flat-key compatibility

## 12. Guardrails

- do not reintroduce fine-grained rule allowlists as the primary rollout model
- do not move connection secrets into checked-in repo config
- do not mix source-specific producer settings back into broad top-level app
  policy
- do not require existing review-only repos to migrate immediately

## 13. Future Config Change Management

Once review and remediation are live across more repositories, config changes
will become rollout coordination work rather than isolated repo cleanup.

That means the product will likely need a clearer config-evolution story later.

Recommended future direction:

- keep compatibility loading as the first migration layer
- add deprecation warnings for legacy keys during startup or CLI validation
- consider an explicit config schema/version once the shape stabilizes further
- add a lightweight config validation or "doctor" command that can:
  - confirm the config is valid
  - highlight deprecated keys
  - point operators toward the current preferred shape

This is not required to complete the first nested config migration, but it
should be treated as the natural follow-on once multiple live repos depend on
the same evolving config contract.
