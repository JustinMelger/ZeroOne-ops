Machine-managed remediation and review items for this repository.

## Open Candidates

### Overview

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 1 | 0 | 0 | 1 | 0 |

### Queue Auto-fix

| Item | File | Priority | Next Step | Summary |
|---|---|---|---|---|
| `sonar:3` | `service.py` | Low | Queue Auto-fix | Simplify boolean comparison |

### Needs Review

| Item | File | Priority | Next Step | Summary |
|---|---|---|---|---|
| `sonar:4` | `worker.py` | High | Investigate Failure | Merge request metadata is inaccessible |

### In Flight

No items.

### Completed

No items.

### Dismissed

No items.

### Work Type Breakdown

| Work Type | Count |
|---|---|
| Investigate failure | 1 |
| Simplify boolean comparison | 1 |

<details>
<summary><code>sonar:3</code> details</summary>

```json
{
  "id": "sonar:3",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-3",
  "file": "src/service.py",
  "line": 42,
  "rule": "python:S1125"
}
```

</details>

<details>
<summary><code>sonar:4</code> details</summary>

```json
{
  "id": "sonar:4",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "failed",
  "title": "Investigate failure",
  "summary": "Merge request metadata is inaccessible from GitLab.",
  "priority": "high",
  "source_reference": "issue-4",
  "file": "src/worker.py",
  "line": 8,
  "rule": "python:S1481",
  "log_excerpt": "Merge request metadata is inaccessible from GitLab."
}
```

</details>
