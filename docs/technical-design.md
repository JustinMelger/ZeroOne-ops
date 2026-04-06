# AI Sonar Bot Technical Design

## 1. Scope

This document defines the technical design for v1 of the AI Sonar Bot described in [functional-design.md](functional-design.md).

V1 constraints:

- Python implementation
- GitLab only
- SonarQube as the issue source
- one issue processed per run
- local JSON state store
- non-interactive CI execution supported
- low-severity maintainability issues targeted first

## 2. Technical Objectives

- Provide a CLI that can run from a checked-out repository.
- Integrate with SonarQube and GitLab APIs using tokens from environment variables.
- Maintain a durable local state file to avoid duplicate work.
- Use a deterministic execution pipeline with explicit step boundaries.
- Isolate provider integrations so future expansion stays manageable.

## 3. Recommended Stack

- Python 3.13.x
- `uv` for dependency management, virtualenv management, and command execution
- `httpx` for API requests
- `pydantic` for config and data models
- `typer` or `argparse` for CLI
- `ruff` for linting and formatting
- `mypy` for static type checking
- `structlog` or standard `logging` for logs
- `pathlib` for filesystem work
- `subprocess` for validation and git commands
- `json` for the state store

Recommended packaging:

- `pyproject.toml`
- `uv.lock`
- source layout under `src/`

## 4. Repository Layout

```text
ai-sonar-bot/
  docs/
    functional-design.md
    technical-design.md
  src/ai_sonar_bot/
    __init__.py
    cli.py
    settings.py
    logging.py
    runner.py
    models/
      __init__.py
      config.py
      sonar.py
      gitlab.py
      state.py
      analysis.py
    providers/
      __init__.py
      sonar_client.py
      gitlab_client.py
      llm_client.py
    services/
      __init__.py
      issue_intake.py
      analysis_service.py
      execution_service.py
      patch_execution_service.py
      solution_artifact_service.py
      publish_service.py
      issue_selector.py
      context_builder.py
      fix_generator.py
      validator.py
      approval.py
      branch_manager.py
      mr_service.py
      workspace_snapshot.py
      run_state_service.py
      state_store.py
    prompts/
      analyze_issue.txt
      generate_structured_edit.txt
      review_merge_request.txt
    utils/
      __init__.py
      git.py
      command.py
      files.py
      clock.py
  tests/
    unit/
    integration/
  .env.example
  pyproject.toml
  uv.lock
  README.md
  .ai-sonar-bot.json
```

## 5. Runtime Architecture

### 5.1 Main Execution Path

The bot runs as a synchronous pipeline in v1:

1. Load config.
2. Initialize clients and state store.
3. Use `IssueIntakeService` to fetch and select one supported issue.
4. Use `ExecutionService` to coordinate branch creation, approval, commit, and handoff to publish.
5. Use `AnalysisService` to build code context, choose the active LLM backend, and render a patch from a structured edit.
6. Use `PatchExecutionService` to apply changes, run validation commands, retry once on failure, and roll back the working tree before commit.
7. In local mode, stop after a validated local commit.
8. In CI mode, use `PublishService` to push the branch and create or reuse a GitLab merge request.
9. Use `RunStateService` to persist run and issue lifecycle updates.

The current implementation follows this path. The remaining approval work is
limited to an optional local interactive mode.

### 5.2 Execution Diagram

```mermaid
flowchart TD
    A[CLI Entry] --> B[Load Settings]
    B --> C[Create Service Container]
    C --> D[Read State File]
    D --> E[IssueIntakeService]
    E --> F{Issue found?}
    F -- No --> G[RunStateService]
    G --> H[Exit cleanly]
    F -- Yes --> I[ExecutionService]
    I --> J[Create Work Branch]
    J --> K[AnalysisService]
    K --> L[LLM Analysis and Bot-Rendered Patch]
    L --> M[PatchExecutionService]
    M --> N[Run Validation Commands]
    N --> O{Validation pass?}
    O -- No --> P[Optional single retry]
    P --> Q{Recovered?}
    Q -- No --> R[RunStateService]
    O -- Yes --> S{Execution mode}
    Q -- Yes --> S
    S -- CI --> T[Commit, PublishService, Create or Reuse GitLab MR]
    S -- Local --> U[Create Local Commit]
    T --> V[RunStateService]
    U --> V
    R --> W[Exit]
    V --> W
```

## 6. Python Module Responsibilities

### 6.1 `cli.py`

Responsibilities:

- parse CLI arguments,
- load settings file path overrides,
- invoke the runner,
- return exit codes.

Suggested commands:

- `ai-sonar-bot run`
- `ai-sonar-bot run --dry-run`
- `ai-sonar-bot run --issue-key <key>`
- `ai-sonar-bot run --mode ci`
- `ai-sonar-bot approve --run-id <id>` for a future non-interactive workflow

For v1, only `run` is required.

### 6.2 `runner.py`

Responsibilities:

- act as the composition root,
- wire together state, intake, and execution services,
- build the final CLI-facing run summary.

This module should stay thin. Workflow details should move into dedicated
services once they are non-trivial.

### 6.3 `settings.py`

Responsibilities:

- read environment variables,
- read optional local config JSON,
- build validated runtime settings objects.

### 6.4 `providers/sonar_client.py`

Responsibilities:

- call SonarQube REST APIs,
- normalize issue payloads,
- expose typed methods for search and detail retrieval.

### 6.5 `providers/gitlab_client.py`

Responsibilities:

- create merge requests,
- look up existing open merge requests for the generated branch,
- use `CI_PROJECT_ID` as a fallback when `GITLAB_PROJECT_ID` is not set in GitLab CI,
- optionally add labels, assignees, or reviewers later.

### 6.6 `providers/llm_client.py`

Responsibilities:

- send structured prompts,
- enforce response format,
- return parsed analysis and structured edit data.

### 6.7 `services/issue_intake.py`

Responsibilities:

- fetch SonarQube issues from the configured source,
- filter out issues that do not map to local files,
- delegate final prioritization to the issue selector,
- return a typed result with selection outcome and issue counts.

### 6.8 `services/analysis_service.py`

Responsibilities:

- build source context for the selected issue,
- choose the active LLM backend,
- coordinate issue analysis and structured edit generation,
- render a patch proposal from a structured edit,
- enforce rejection rules for manual-only issues,
- delegate artifact persistence and patch execution to focused services.

### 6.9 `services/execution_service.py`

Responsibilities:

- coordinate the post-intake workflow for one selected issue,
- create a local branch when required,
- call the analysis service,
- create a local commit after successful validation,
- request local approval when configured,
- delegate branch push and merge request creation to the publish service in CI mode.

### 6.10 `services/patch_execution_service.py`

Responsibilities:

- apply bot-rendered patches,
- run validation commands,
- retry once on failure,
- restore the working tree before commit on patch-apply or validation failure.

### 6.11 `services/solution_artifact_service.py`

Responsibilities:

- persist optional local solution artifacts for debugging,
- keep artifact policy and file writing out of the LLM provider layer.

### 6.12 `services/publish_service.py`

Responsibilities:

- push the prepared branch,
- create or reuse a GitLab merge request,
- build the deterministic merge request description template.

### 6.13 `services/issue_selector.py`

Responsibilities:

- filter unsupported SonarQube issues,
- avoid already-processed items,
- rank issues,
- return the single selected issue.

### 6.14 `services/context_builder.py`

Responsibilities:

- load the target file,
- capture neighboring lines,
- identify related test files when possible,
- include validation command metadata in the LLM context.

### 6.12 `services/fix_generator.py`

Responsibilities:

- build prompts,
- request issue analysis,
- request a patch,
- validate patch boundaries before apply.

### 6.13 `services/validator.py`

Responsibilities:

- run configured shell commands,
- stream or capture output,
- summarize failures for retry prompts.

### 6.14 `services/approval.py`

Responsibilities:

- present a summary to the operator,
- request explicit approval in the terminal,
- return approved or rejected.

This service should be bypassed in CI mode.

### 6.15 `services/branch_manager.py`

Responsibilities:

- ensure clean enough git state for execution,
- create local branches,
- commit changes,
- push to origin.

### 6.16 `services/mr_service.py`

Responsibilities:

- assemble merge request title and description,
- look up an existing open merge request for the work branch,
- call GitLab client to create the MR only when reuse is not possible,
- attach issue metadata in a consistent template.

### 6.17 `services/run_state_service.py`

Responsibilities:

- append and update run records,
- persist issue lifecycle transitions,
- centralize structured failure persistence,
- build user-facing run summaries consistently.

### 6.18 `services/state_store.py`

Responsibilities:

- load and save the JSON file,
- manage issue lock state,
- record run history and issue outcomes.

## 7. Configuration Design

## 7.1 Sources

Configuration should come from:

- environment variables for secrets,
- `.ai-sonar-bot.json` for non-secret runtime settings,
- CLI flags for run-time overrides.

Precedence order:

1. CLI flags
2. Environment variables
3. `.ai-sonar-bot.json`

GitLab project resolution:

- use `GITLAB_PROJECT_ID` when explicitly configured,
- otherwise use GitLab CI's `CI_PROJECT_ID` when available.
4. defaults

## 7.2 Environment Variables

Required:

- `SONARQUBE_URL`
- `SONARQUBE_TOKEN`
- `SONARQUBE_PROJECT_KEY`
- `GITLAB_URL`
- `GITLAB_TOKEN`
- `GITLAB_PROJECT_ID` or GitLab CI `CI_PROJECT_ID`
- `LLM_API_KEY`

Optional:

- `AI_SONAR_BOT_CONFIG`
- `AI_SONAR_BOT_STATE_PATH`
- `AI_SONAR_BOT_LOG_LEVEL`
- `AI_SONAR_BOT_BASE_BRANCH`
- `AI_SONAR_BOT_EXECUTION_MODE`

## 7.3 Runtime Config File

Example `.ai-sonar-bot.json`:

```json
{
  "base_branch": "main",
  "branch_prefix": "ai-sonar",
  "execution_mode": "ci",
  "dry_run": false,
  "max_retry_count": 1,
  "supported_severities": ["BLOCKER", "CRITICAL", "MAJOR"],
  "supported_issue_types": ["CODE_SMELL", "BUG", "VULNERABILITY"],
  "supported_rules": [],
  "validation_commands": [
    "uv run pytest",
    "uv run mypy src",
    "uv run ruff check .",
    "uv run ruff format --check ."
  ],
  "analysis": {
    "context_lines_before": 40,
    "context_lines_after": 40,
    "max_file_bytes": 200000
  },
  "approval": {
    "required": true
  },
  "gitlab": {
    "target_branch": "main",
    "labels": ["ai-sonar-bot", "sonarqube"]
  },
  "state": {
    "path": ".ai-sonar-bot-state.json"
  }
}
```

## 7.4 Pydantic Settings Model

Suggested top-level model:

```python
class AppConfig(BaseModel):
    execution_mode: Literal["local", "ci"] = "ci"
    base_branch: str
    branch_prefix: str = "ai-sonar"
    dry_run: bool = False
    max_retry_count: int = 1
    supported_severities: list[str]
    supported_issue_types: list[str]
    supported_rules: list[str] = []
    validation_commands: list[str]
    analysis: AnalysisConfig
    approval: ApprovalConfig
    gitlab: GitLabConfig
    state: StateConfig
```

## 8. Data Model Design

## 8.1 SonarQube Issue Model

```python
class SonarIssue(BaseModel):
    key: str
    rule: str
    severity: str
    type: str
    status: str
    message: str
    component: str
    project: str
    file_path: str
    line: int | None = None
    effort: str | None = None
    tags: list[str] = []
    creation_date: datetime | None = None
```

`file_path` should be normalized to a repository-relative path.

## 8.2 Analysis Result Model

```python
class IssueAnalysis(BaseModel):
    issue_key: str
    classification: Literal["auto_fixable", "retryable", "manual"]
    summary: str
    risk_notes: list[str]
    target_files: list[str]
    proposed_strategy: str
```

## 8.3 Structured Edit Model

```python
class TextEdit(BaseModel):
    file_path: str
    search_text: str
    replace_text: str
    line_hint: int | None = None

class StructuredEditProposal(BaseModel):
    issue_key: str
    edits: list[TextEdit]
    commit_message: str
    mr_title: str
    mr_description: str
```

For v1, the LLM returns structured edits instead of a raw diff. The bot verifies
that each edit is narrow and unambiguous, applies it in memory, and renders the
unified diff itself.

## 8.4 Patch Result Model

```python
class PatchProposal(BaseModel):
    issue_key: str
    files_touched: list[str]
    unified_diff: str
    commit_message: str
    mr_title: str
    mr_description: str
```

For v1, `PatchProposal` is a bot-rendered artifact produced from a validated
`StructuredEditProposal`. The bot applies it locally and rejects patches that
touch files outside the repository.

## 8.5 Validation Result Model

```python
class ValidationCommandResult(BaseModel):
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int

class ValidationResult(BaseModel):
    passed: bool
    results: list[ValidationCommandResult]
    summary: str
```

## 8.6 Run State Model

```python
class RunStatus(str, Enum):
    STARTED = "started"
    NO_ISSUE = "no_issue"
    SELECTED = "selected"
    ANALYZING = "analyzing"
    FIX_GENERATED = "fix_generated"
    VALIDATION_FAILED = "validation_failed"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    MR_CREATED = "mr_created"
    MANUAL = "manual"
    FAILED = "failed"

class RunRecord(BaseModel):
    run_id: str
    issue_key: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    mr_url: str | None = None
    status: RunStatus
    started_at: datetime
    updated_at: datetime
    error_message: str | None = None
```

## 9. State Store Design

## 9.1 File Location

Default path:

- `.ai-sonar-bot-state.json`

The file lives in the repository root so it is easy to inspect locally. It should not be committed by default.

## 9.2 File Structure

The structure should be simple and Renovate-like: top-level metadata plus itemized tracked objects.

Example:

```json
{
  "version": 1,
  "updated_at": "2026-03-27T10:00:00Z",
  "repository": {
    "base_branch": "main",
    "gitlab_project_id": "12345",
    "sonarqube_project_key": "sample-project"
  },
  "active_issue_key": null,
  "runs": [
    {
      "run_id": "20260327T100000Z-7f2db3a1",
      "issue_key": "AX12345",
      "status": "mr_created",
      "branch_name": "ai-sonar/AX12345-null-check",
      "commit_sha": "abc123",
      "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/14",
      "started_at": "2026-03-27T10:00:00Z",
      "updated_at": "2026-03-27T10:04:12Z",
      "error_message": null
    }
  ],
  "issues": {
    "AX12345": {
      "status": "mr_created",
      "last_run_id": "20260327T100000Z-7f2db3a1",
      "branch_name": "ai-sonar/AX12345-null-check",
      "mr_url": "https://gitlab.example.com/group/project/-/merge_requests/14",
      "attempt_count": 1,
      "last_error": null,
      "updated_at": "2026-03-27T10:04:12Z"
    }
  }
}
```

## 9.3 State Semantics

- `active_issue_key` prevents concurrent work in a single shared state file.
- `runs` provides an append-only execution log.
- `issues` stores the latest lifecycle state per SonarQube issue.

Issue lifecycle values:

- `selected`
- `manual`
- `validation_failed`
- `rejected`
- `mr_created`
- `failed`

## 9.4 Write Strategy

To avoid state corruption:

1. Read current JSON.
2. Modify in memory.
3. Write to a temporary file in the same directory.
4. Atomically replace the original file.

## 10. SonarQube Integration Design

## 10.1 API Endpoints

Primary endpoint:

- `GET /api/issues/search`

Suggested query parameters:

- `projects=<SONARQUBE_PROJECT_KEY>`
- `statuses=OPEN,REOPENED,CONFIRMED`
- `ps=100`

Optional narrowing:

- `types=CODE_SMELL,BUG,VULNERABILITY`
- `severities=BLOCKER,CRITICAL,MAJOR`

Future endpoint:

- `GET /api/issues/show`

Used only if the search payload is insufficient.

## 10.2 SonarQube Client Interface

```python
class SonarClient(Protocol):
    def search_open_issues(self) -> list[SonarIssue]: ...
    def get_issue(self, issue_key: str) -> SonarIssue: ...
```

## 10.3 Issue Normalization Rules

- Strip project prefixes from SonarQube component paths when needed.
- Normalize separators to POSIX-style relative paths.
- Reject issues whose files do not exist in the local repository.
- Preserve original raw fields for logging if useful.

## 11. GitLab Integration Design

## 11.1 API Endpoints

Primary endpoint:

- `POST /api/v4/projects/:id/merge_requests`

Potential secondary endpoints later:

- add labels or reviewers,
- comment on existing MRs,
- detect duplicate open MRs.

## 11.2 GitLab Client Interface

```python
class GitLabClient(Protocol):
    def create_merge_request(
        self,
        project_id: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
    ) -> MergeRequestInfo: ...
```

## 11.3 Duplicate MR Prevention

Duplicate prevention should rely primarily on local state in v1.

Optional safety check:

- query GitLab for an open MR from the same source branch before creating a new one.

## 12. LLM Integration Design

## 12.1 Prompt Inputs

The LLM request should include:

- SonarQube issue metadata,
- repository-relative target file path,
- focused code snippet around the target line,
- optional whole file content when under size threshold,
- related test file snippets when found,
- validation commands,
- instructions to minimize change scope,
- required response schema.

## 12.2 Response Format

Use structured JSON for analysis plus a structured edit proposal. Example:

```json
{
  "analysis": {
    "classification": "auto_fixable",
    "summary": "Add a null check before dereferencing the response object.",
    "risk_notes": ["Behavior changes if callers rely on exception flow."],
    "target_files": ["src/service.py"],
    "proposed_strategy": "Return early when the response is None."
  },
  "structured_edit": {
    "edits": [
      {
        "file_path": "src/service.py",
        "search_text": "if enabled == True:",
        "replace_text": "if enabled:",
        "line_hint": 14
      }
    ]
  },
  "metadata": {
    "commit_message": "fix: handle nullable response in service",
    "mr_title": "fix: handle nullable response in service",
    "mr_description": "## Summary\n...\n## SonarQube Issue\n..."
  }
}
```

## 12.3 Guardrails

- Reject responses missing required fields.
- Reject structured edits that touch paths outside the repository.
- Reject edits that cannot be applied unambiguously.
- Reject edits larger than a configured file count or byte size.
- Reject empty edits for issues classified as auto-fixable.
- Include validation failure output in the retry prompt when the edit must be regenerated.

## 13. Patch Application Design

## 13.1 Strategy

Preferred v1 strategy:

- request a structured edit proposal from the LLM,
- verify exact search-and-replace operations against the target file,
- apply the edit in memory,
- render a unified diff in the bot,
- apply the rendered diff with `git apply`,
- inspect the result before validation.

## 13.2 Safety Checks

Before applying a patch:

- verify branch is not the base branch,
- verify target files are inside repo root,
- verify no forbidden paths are touched, such as `.git/`,
- verify each structured edit matches exactly one location unless `line_hint`
  disambiguates it,
- verify file count is within the configured maximum.

## 14. Git Workflow Design

## 14.1 Branch Naming

Format:

- `ai-sonar/<issue-key>-<slug>`

Example:

- `ai-sonar/AX12345-null-check`

Slug source:

- sanitized fragment from issue message or rule.

## 14.2 Local Git Preconditions

The branch manager should:

- verify the current repo is a git repository,
- verify the base branch exists locally,
- verify there are no conflicting staged changes,
- fail fast if the working tree is too dirty for safe automation.

Reasonable v1 rule:

- allow untracked files,
- reject modified tracked files unless running in a dedicated clean clone.

## 14.3 Commit Message

Format:

- `fix(sonar): <short description> [<issue-key>]`

Example:

- `fix(sonar): add null guard to service response [AX12345]`

## 15. Validation Design

## 15.1 Command Execution

Validation commands should run:

- sequentially,
- from repository root,
- with captured stdout and stderr,
- with a per-command timeout.

Suggested timeout:

- 10 minutes per command in v1

## 15.2 Result Handling

If any command fails:

1. capture all outputs,
2. summarize the failure,
3. if retry count is below max, send feedback to the LLM,
4. otherwise mark the issue as `validation_failed`.

## 16. Approval Model

## 16.1 CI Mode

In CI mode:

- validation success should lead directly to branch push and merge request creation,
- there must be no interactive terminal prompt,
- GitLab merge request review is the human approval mechanism.

## 16.2 Local Mode

After validation passes, the CLI should show:

- issue key and message,
- files changed,
- validation command summary,
- git diff summary,
- proposed commit message,
- proposed MR title.

Prompt:

- `Create merge request? [y/N]:`

If the user answers:

- `y` or `yes`: continue
- anything else: stop and persist state as `rejected`

## 16.3 Approval Diagram

```mermaid
sequenceDiagram
    participant Runner
    participant Validator
    participant Operator
    participant Git
    participant GitLab

    Runner->>Validator: Run configured checks
    Validator-->>Runner: Validation passed
    Runner->>Operator: Display change summary and ask approval
    Operator-->>Runner: yes / no
    alt Approved
        Runner->>Git: Commit and push branch
        Runner->>GitLab: Create merge request
        GitLab-->>Runner: MR URL
    else Rejected
        Runner-->>Runner: Persist rejected status
    end
```

## 17. Logging and Error Handling

## 17.1 Logging Fields

Every log event should include:

- `run_id`
- `issue_key` when available
- `step`
- `status`
- `duration_ms` when relevant

## 17.2 Exception Strategy

Use typed exceptions for:

- configuration errors,
- SonarQube API failures,
- GitLab API failures,
- git command failures,
- patch application failures,
- validation failures,
- approval rejection,
- state store read/write failures.

The runner catches these and maps them to terminal statuses.

## 18. Testing Strategy

## 18.1 Unit Tests

Cover:

- issue selection rules,
- config parsing,
- state store load/save,
- SonarQube payload normalization,
- GitLab request payload building,
- approval parsing,
- validation result summarization.

## 18.2 Integration Tests

Cover:

- reading config and executing a dry run,
- applying a known patch fixture,
- state file transitions across a successful mocked run,
- failure transitions on validation error.

## 18.3 Mocking Strategy

- mock SonarQube responses,
- mock GitLab MR creation,
- mock LLM responses with fixed JSON fixtures,
- run validation commands against test-safe commands.

## 19. Implementation Sequence

Recommended order:

1. Scaffold package, CLI, and settings.
2. Implement models and JSON state store.
3. Implement SonarQube client and issue selection.
4. Extract issue intake and analysis orchestration into dedicated services.
5. Implement git branch manager and validation runner.
6. Implement LLM integration and patch application.
7. Implement CI execution mode and optional local approval flow.
8. Implement GitLab MR creation.
9. Add duplicate-MR safeguards and clearer publish failure handling.
10. Add dry-run behavior and tests.

## 20. Open Technical Risks

- LLM-generated patches may not apply cleanly.
- SonarQube file paths may not map directly to local paths.
- Some issues may need broader repository context than the default prompt size.
- Validation commands may be slow or side-effectful in some repositories.
- A local JSON state file is simple but not safe for multi-runner concurrency.

## 21. V1 Exit Criteria

The technical design is complete when implementation can be started with no unresolved questions about:

- module boundaries,
- runtime config inputs,
- JSON state structure,
- SonarQube and GitLab API usage,
- approval flow,
- patch application strategy,
- validation and error handling behavior.

## 23. Pipeline Execution

The intended deployment model for v1 is a non-interactive pipeline job, likely inside Docker.

Pipeline requirements:

- repository checkout available in the container workspace,
- git installed and authenticated for push,
- SonarQube, GitLab, and OpenAI credentials injected through environment variables,
- no terminal interaction required,
- one issue processed per execution.

Recommended behavior:

- run on a schedule or manual trigger,
- create at most one merge request per execution,
- rely on GitLab merge request review and approval rules for human sign-off.

## 22. Packaging and Developer Tooling Decisions

These decisions are fixed for v1:

- use `uv` for project initialization, dependency installation, locking, and command execution,
- use `pyproject.toml` as the single project configuration file,
- commit `uv.lock` to keep dependency resolution reproducible,
- use `ruff check` for linting,
- use `ruff format` for formatting,
- use `mypy` for static type checking,
- run quality checks through `uv run`.

Recommended developer commands:

- `uv sync`
- `uv run pytest`
- `uv run mypy src`
- `uv run ruff check .`
- `uv run ruff format .`
