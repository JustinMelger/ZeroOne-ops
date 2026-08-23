# Runtime Workspace Ownership

## Status

Current technical contract for remediation workspace safety.

## Purpose

Remediation runs can generate local state and scanner artifacts before branch
creation. Those exact configured outputs must not require repository
`.gitignore` entries, while all real workspace changes remain protected.

## Ownership Rule

The provider-neutral remediation execution path derives owned output paths from
`state.path`, `sarif.artifacts[].path`, and `openai_solution_output_path`.
Each path must be relative, non-traversing, and resolve inside the remediation
repository. Ownership is exact-path only.

Only an untracked Git porcelain entry (`??`) whose normalized path exactly
matches a configured output is ignored. Directory prefixes, globs, absolute or
escaping configuration paths, and unconfigured files under an artifact
directory are never exempt.

Tracked modifications, staging, deletion, rename, copy, and conflict states
always block remediation, including when they affect a configured output path.
The implementation never cleans, stages, deletes, or adds `.gitignore` rules.

## Enforcement

Both remediation workspace guards use the same NUL-delimited Git porcelain
parser and ownership policy:

1. `BranchManager.ensure_ready()` protects branch creation.
2. `PatchExecutionService` verifies validation setup has not dirtied the
   repository before patch application.

Ignored configured outputs are logged with bounded path details. Remaining
blocking changes continue through the existing persisted branch-preparation or
validation-setup failure evidence.

## Provider Boundary

GitHub and GitLab do not implement workspace filtering. Both use the shared
remediation execution path, so the ownership rule and dirty-workspace behavior
remain identical across providers.
