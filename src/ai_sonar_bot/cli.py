"""CLI entrypoint.

This module exposes the Typer application used to run the bot from the shell.
"""

from __future__ import annotations

import json

import typer
from typer import Context

from ai_sonar_bot.logging import configure_logging
from ai_sonar_bot.runner import (
    add_remediation_exclusion,
    dashboard_reconcile,
    dashboard_remediate,
    list_remediation_exclusions,
    remove_remediation_exclusion,
    review,
    sync_dashboard_sonar,
)

app = typer.Typer(add_completion=False, help="ZeroOne Ops CLI.")
review_app = typer.Typer(add_completion=False, help="Merge request review workflow.")
dashboard_app = typer.Typer(add_completion=False, help="Dashboard sync workflows.")
exclusions_app = typer.Typer(add_completion=False, help="Remediation exclusion policy.")
app.add_typer(review_app, name="review")
app.add_typer(dashboard_app, name="dashboard")
dashboard_app.add_typer(exclusions_app, name="exclusions")


def _echo_review_summary(*, dry_run: bool) -> None:
    """Run the review workflow and print the CLI-facing summary."""
    configure_logging()
    summary = review(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    if summary.issue_key is not None:
        typer.echo(f"issue_key={summary.issue_key}")
    if summary.dashboard_item_id is not None:
        typer.echo(f"dashboard_item_id={summary.dashboard_item_id}")
    if summary.branch_name is not None:
        typer.echo(f"branch_name={summary.branch_name}")
    if summary.commit_sha is not None:
        typer.echo(f"commit_sha={summary.commit_sha}")
    if summary.mr_url is not None:
        typer.echo(f"mr_url={summary.mr_url}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


def _echo_dashboard_summary(*, dry_run: bool) -> None:
    """Run one dashboard workflow and print the CLI-facing summary."""
    configure_logging()
    summary = sync_dashboard_sonar(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    if summary.issue_key is not None:
        typer.echo(f"issue_key={summary.issue_key}")
    if summary.dashboard_item_id is not None:
        typer.echo(f"dashboard_item_id={summary.dashboard_item_id}")
    if summary.branch_name is not None:
        typer.echo(f"branch_name={summary.branch_name}")
    if summary.commit_sha is not None:
        typer.echo(f"commit_sha={summary.commit_sha}")
    if summary.mr_url is not None:
        typer.echo(f"mr_url={summary.mr_url}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


@app.callback(invoke_without_command=True)
def root_command(
    ctx: Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without changing repository state."),
) -> None:
    """Show help when no subcommand is provided."""
    del dry_run
    if ctx.invoked_subcommand is not None:
        return
    typer.echo(ctx.get_help())


@review_app.callback(invoke_without_command=True)
def review_command(
    ctx: Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing a review note."),
) -> None:
    """Run the merge-request review workflow."""
    if ctx.invoked_subcommand is not None:
        return
    _echo_review_summary(dry_run=dry_run)


@dashboard_app.command("sonar")
def dashboard_sonar_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without updating the dashboard."),
) -> None:
    """Sync eligible SonarQube issues into the dashboard."""
    _echo_dashboard_summary(dry_run=dry_run)


@dashboard_app.command("remediate")
def dashboard_remediate_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing remediation."),
) -> None:
    """Run the dashboard-backed remediation workflow."""
    configure_logging()
    summary = dashboard_remediate(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    if summary.issue_key is not None:
        typer.echo(f"issue_key={summary.issue_key}")
    if summary.dashboard_item_id is not None:
        typer.echo(f"dashboard_item_id={summary.dashboard_item_id}")
    if summary.branch_name is not None:
        typer.echo(f"branch_name={summary.branch_name}")
    if summary.commit_sha is not None:
        typer.echo(f"commit_sha={summary.commit_sha}")
    if summary.mr_url is not None:
        typer.echo(f"mr_url={summary.mr_url}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


@dashboard_app.command("reconcile")
def dashboard_reconcile_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without updating dashboard lifecycle.",
    ),
) -> None:
    """Run the dashboard reconciliation workflow."""
    configure_logging()
    summary = dashboard_reconcile(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    if summary.issue_key is not None:
        typer.echo(f"issue_key={summary.issue_key}")
    if summary.dashboard_item_id is not None:
        typer.echo(f"dashboard_item_id={summary.dashboard_item_id}")
    if summary.branch_name is not None:
        typer.echo(f"branch_name={summary.branch_name}")
    if summary.commit_sha is not None:
        typer.echo(f"commit_sha={summary.commit_sha}")
    if summary.mr_url is not None:
        typer.echo(f"mr_url={summary.mr_url}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


@exclusions_app.command("list")
def dashboard_exclusions_list_command() -> None:
    """List persisted remediation exclusions."""
    exclusions, state_path = list_remediation_exclusions()
    typer.echo(f"count={len(exclusions)}")
    typer.echo(f"state_path={state_path}")
    for exclusion in exclusions:
        typer.echo(
            json.dumps(
                {
                    "source": exclusion.source,
                    "issue_key": exclusion.issue_key,
                    "scope": exclusion.scope,
                    "reason": exclusion.reason,
                    "updated_at": exclusion.updated_at.isoformat(),
                    "updated_by": exclusion.updated_by,
                },
                sort_keys=True,
            )
        )


@exclusions_app.command("add")
def dashboard_exclusions_add_command(
    source: str = typer.Option(..., "--source", help="Source family such as sonarqube."),
    issue_key: str = typer.Option(..., "--issue-key", help="Source-specific exclusion key."),
    reason: str = typer.Option(..., "--reason", help="Short operator reason for the exclusion."),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="Optional bounded scope such as a path prefix.",
    ),
    updated_by: str | None = typer.Option(
        None,
        "--updated-by",
        help="Optional operator identity.",
    ),
) -> None:
    """Add or replace one persisted remediation exclusion."""
    exclusion, created, state_path = add_remediation_exclusion(
        source=source,
        issue_key=issue_key,
        reason=reason,
        scope=scope,
        updated_by=updated_by,
    )
    typer.echo(f"state_path={state_path}")
    typer.echo(f"action={'created' if created else 'replaced'}")
    typer.echo(
        json.dumps(
            {
                "source": exclusion.source,
                "issue_key": exclusion.issue_key,
                "scope": exclusion.scope,
                "reason": exclusion.reason,
                "updated_at": exclusion.updated_at.isoformat(),
                "updated_by": exclusion.updated_by,
            },
            sort_keys=True,
        )
    )


@exclusions_app.command("remove")
def dashboard_exclusions_remove_command(
    source: str = typer.Option(..., "--source", help="Source family such as sonarqube."),
    issue_key: str = typer.Option(..., "--issue-key", help="Source-specific exclusion key."),
    scope: str | None = typer.Option(
        None,
        "--scope",
        help="Optional bounded scope such as a path prefix.",
    ),
) -> None:
    """Remove one persisted remediation exclusion."""
    exclusion, removed, state_path = remove_remediation_exclusion(
        source=source,
        issue_key=issue_key,
        scope=scope,
    )
    typer.echo(f"state_path={state_path}")
    typer.echo(f"removed={str(removed).lower()}")
    if exclusion is not None:
        typer.echo(
            json.dumps(
                {
                    "source": exclusion.source,
                    "issue_key": exclusion.issue_key,
                    "scope": exclusion.scope,
                    "reason": exclusion.reason,
                    "updated_at": exclusion.updated_at.isoformat(),
                    "updated_by": exclusion.updated_by,
                },
                sort_keys=True,
            )
        )


def main() -> None:
    """Start the CLI application."""
    app()


if __name__ == "__main__":
    main()
