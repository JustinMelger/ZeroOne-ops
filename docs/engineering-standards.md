## Engineering Standards

This document defines the coding standards for ZeroOne Ops v1. The goal is to keep the codebase easy to reason about while the implementation grows from scaffold to production workflow.

## 1. Core Principles

- Prefer simple, explicit code over clever abstractions.
- Keep behavior close to the domain concept that owns it.
- Push side effects to the edges of the system.
- Optimize for testability and readability first.
- Add abstractions only when they remove real duplication or isolate real variability.

## 2. Layering Rules

The repository is organized into these layers:

- `models`
  - Typed domain and configuration objects only.
  - No business logic beyond simple validation or convenience methods.
- `providers`
  - External system adapters only.
  - Translate HTTP, SDK, or file-system payloads into typed models.
  - Must not contain business policy or orchestration logic.
- `services`
  - Application and domain behavior.
  - Coordinate models and providers to perform one focused responsibility.
- `runner`
  - Composition root for the main execution flow.
  - Wires services together and controls high-level sequencing.
- `cli`
  - Argument parsing and terminal output only.

Rules:

- `models` must not import `services` or `providers`.
- `providers` must not import `services`.
- `cli` must not contain business logic.
- `runner` must not become a catch-all implementation file; orchestration should move into services once the logic becomes non-trivial.

## 3. OOP Guidelines

- Use a class only when it represents a clear concept with owned behavior.
- Prefer composition over inheritance.
- Avoid inheritance unless there is a real subtype relationship.
- Keep constructors cheap.
- Do not perform network I/O, subprocess execution, or file writes in `__init__`.
- Favor stateless services where possible.
- Prefer explicit dependencies passed into constructors over hidden globals.

Use classes for:

- API clients
- stateful adapters
- focused services with a clear responsibility

Do not use classes for:

- unrelated utility function groupings
- passive namespaces
- wrappers that only forward one call without adding value

## 4. Method and Class Design

- A class should have one clear reason to change.
- Public methods should describe outcomes, not implementation details.
- Methods should stay small enough to scan quickly.
- If a method needs many branches, extract a collaborator or split the operation.
- Avoid boolean-flag-driven behavior when separate methods or strategies are clearer.

Preferred examples:

- `select_issue()`
- `build_context()`
- `create_merge_request()`
- `apply_patch()`

Avoid names like:

- `handle()`
- `process()`
- `do_work()`

unless the class context makes the meaning precise.

## 5. State and Side Effects

- Keep mutation localized and explicit.
- Do not read environment variables outside `settings.py`.
- Do not run subprocesses outside dedicated command or git-related services.
- Do not perform ad hoc JSON or file writes in business logic when a dedicated service already owns that responsibility.
- Return typed results instead of mutating shared global state.

## 6. Types and Data Contracts

- Use typed models for data crossing service boundaries.
- Avoid passing raw `dict[str, Any]` through the application when a model should exist.
- Keep optional fields truly optional; do not overload empty strings to mean missing.
- Use `Literal`, enums, and narrow types when the domain is constrained.
- Keep conversion from external payloads to internal models at provider boundaries.

## 7. Error Handling

- Raise specific exceptions for domain failures.
- Do not use bare `Exception` unless re-raising with context at a system boundary.
- Error messages should explain what failed and why.
- Fail fast on invalid configuration.
- Distinguish operational failures from domain decisions.

Examples:

- missing credentials is a configuration error
- rejected patch generation is a workflow decision
- failed HTTP request is an operational error

## 8. Testing Standards

- Tests should mirror the source tree.
- Prefer unit tests for business decisions and pure logic.
- Add integration tests for orchestration and provider interactions.
- Every bug fix should include a regression test when practical.
- Mock external systems at the provider boundary, not deep inside business logic.
- Avoid tests that assert private implementation details when public behavior is sufficient.

Coverage priorities:

- selection logic
- context generation
- patch validation and application safety
- configuration loading
- publish and MR decision flow

## 9. Naming Standards

- Use names from the domain, not generic technical placeholders.
- Prefer `issue`, `patch`, `analysis`, `merge_request`, `state`, `validation_result`.
- Avoid vague names like `data`, `item`, `manager`, `helper`, or `handler` unless the role is genuinely generic.
- File names should match the main concept in the file.

## 10. Docstrings and Comments

- Use Google-style docstrings for public modules, classes, and functions.
- Comments should explain intent or a non-obvious constraint.
- Do not add comments that restate the code.
- Keep docstrings aligned with real behavior; update them when behavior changes.

## 11. Dependency and Abstraction Discipline

- Add a dependency only when it meaningfully reduces complexity or maintenance cost.
- Prefer standard library solutions unless a library solves a real problem better.
- Introduce interfaces or protocols only where multiple implementations are realistic.
- Do not generalize early for hypothetical future providers or execution modes.

## 12. Refactoring Rule

When adding a feature:

- If the change fits the current structure cleanly, keep it simple.
- If the change makes a class or method noticeably harder to understand, refactor in the same change.
- Do not leave obvious structural debt in place if the fix is small and local.

## 13. Current Design Direction

As the codebase grows, prefer moving orchestration out of `runner.py` into focused services such as:

- `IssueIntakeService`
- `AnalysisService`
- `ValidationService`
- `PublishService`

These are targets, not mandatory abstractions today. Add them when the current logic becomes large enough to justify the split.
