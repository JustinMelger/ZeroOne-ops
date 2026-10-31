# Troubleshooting

Start with the work-item issue's **Last Execution**, **Recovery**, or
**Selection** evidence where present. Follow its workflow-log link for the full
CI context. The [common outcomes](runbook.md#common-outcomes) distinguish a
healthy no-work result from an execution failure.

## Find The Failed Stage

| Symptom | Reference |
| --- | --- |
| Configuration is rejected | [Missing Configuration](runbook.md#missing-configuration), [V1 Migration](migration-v1.md) |
| Generated state or scanner files block a branch | [Runtime Workspace Outputs](runbook.md#runtime-workspace-outputs) |
| Dependency setup or validation fails | [Validation Failure](runbook.md#validation-failure), [Toolchain Images](runbook.md#validation-toolchain-images) |
| A generated edit cannot be applied | [Patch Apply Failure](runbook.md#patch-apply-failure) |
| A branch cannot be pushed | [Branch Push Failure](runbook.md#branch-push-failure) |
| Request creation fails | [Merge Request Creation Failure](runbook.md#merge-request-creation-failure) |
| Review context or publication fails | [Review Context Failure](runbook.md#review-context-failure), [Review Note Publication Failure](runbook.md#review-note-publication-failure) |

## Retry Deliberately

Correct the underlying cause before using an advertised recovery command.
Do not repeatedly requeue unchanged work or treat manually closing an issue as
durable dismissal. Follow the authoritative issue's guidance and the
[recovery steps](runbook.md#recovery-steps).

For deeper investigation, use the runbook's [debugging guidance](runbook.md#debugging-guidance).
Keep credentials and raw sensitive command output out of public comments.
