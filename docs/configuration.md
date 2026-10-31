# Configuration

The repository configuration defines workflow behavior; CI variables supply
credentials and integration settings. Do not put tokens in committed JSON files.

## Repository Settings

Use the runbook's [JSON configuration guide](runbook.md#json-config-quick-guide)
and the maintained
[example configurations](https://github.com/JustinMelger/ZeroOne-ops/tree/main/examples).
The [supported v1 scope](runbook.md#supported-v1-scope) describes batching,
capacity, source priorities, and validation behavior.

Configure scanner artifact paths and stable source IDs to match the files your
pipeline actually produces. Scans must run before finding sync. See
[normal operations](runbook.md#normal-operations) for ordering and
[finding dogfood](runbook.md#finding-dogfood) for the repository's own example.

## Credentials And Validation

- Supply the [required CI variables](runbook.md#required-ci-variables) through your provider.
- Apply the [token permission requirements](runbook.md#required-token-permissions).
- Read the [execution trust model](runbook.md#execution-trust-model) before enabling setup commands.
- Select a [validation toolchain image](runbook.md#validation-toolchain-images) that has your tools.
- Review [runtime workspace outputs](runbook.md#runtime-workspace-outputs) when configuring generated files.

Baseline-aware validation is opt-in. Use the runbook's configuration example to
enable it explicitly; publication still requires reliable validation evidence.
See [validation failures](runbook.md#validation-failure) for diagnostics and recovery.

When upgrading, remove retired keys according to the [migration guide](migration-v1.md).
Invalid or unsupported configuration fails explicitly rather than silently
enabling behavior that is not implemented.
