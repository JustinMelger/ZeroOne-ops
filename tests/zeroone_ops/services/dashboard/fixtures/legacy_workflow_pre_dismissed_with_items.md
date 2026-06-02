Machine-managed remediation and review items for this repository.

## Open Candidates

### Overview

| Open | In progress | MR opened | Failed | Done |
|---|---|---|---|---|
| 1 | 1 | 0 | 0 | 0 |

### Queue Auto-fix

| Item | File | Priority | Next Step | Summary |
|---|---|---|---|---|
| `sonar:1` | `service.py` | Low | Queue Auto-fix | Simplify boolean comparison |

### Needs Review

No items.

### In Flight

| Item | Status | Priority | Review Summary |
|---|---|---|---|
| `sonar:2` | 🔧 In Progress | Medium | Update in progress |

### Completed

No items.

### Work Type Breakdown

| Work Type | Count |
|---|---|
| Simplify boolean comparison | 1 |
| Update in progress | 1 |

<details>
<summary><code>sonar:1</code> details</summary>

```json
{
  "id": "sonar:1",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "open",
  "title": "Simplify boolean comparison",
  "summary": "Replace explicit boolean equality with direct truthiness.",
  "priority": "low",
  "source_reference": "issue-1",
  "file": "src/service.py",
  "line": 42,
  "rule": "python:S1125"
}
```

</details>

<details>
<summary><code>sonar:2</code> details</summary>

```json
{
  "id": "sonar:2",
  "source": "sonarqube",
  "type": "code_smell_fix",
  "status": "in_progress",
  "title": "Update in progress",
  "summary": "Current remediation run is in progress.",
  "priority": "medium",
  "source_reference": "issue-2",
  "file": "src/worker.py",
  "line": 8,
  "rule": "python:S1481"
}
```

</details>
