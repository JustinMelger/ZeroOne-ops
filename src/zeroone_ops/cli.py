"""CLI entrypoint.

This module exposes the Typer application used to run the bot from the shell.
"""

from __future__ import annotations

import typer
from typer import Context

from zeroone_ops.logging import configure_logging
from zeroone_ops.runner import (
    dashboard_policy,
    dashboard_reconcile,
    dashboard_remediate,
    review,
    sync_dashboard_sonar,
)

app = typer.Typer(add_completion=False, help="ZeroOne Ops CLI.")
review_app = typer.Typer(add_completion=False, help="Merge request review workflow.")
dashboard_app = typer.Typer(add_completion=False, help="Dashboard sync workflows.")
app.add_typer(review_app, name="review")
app.add_typer(dashboard_app, name="dashboard")


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
    if summary.change_request_url is not None:
        typer.echo(f"change_request_url={summary.change_request_url}")
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
    if summary.change_request_url is not None:
        typer.echo(f"change_request_url={summary.change_request_url}")
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
    if summary.change_request_url is not None:
        typer.echo(f"change_request_url={summary.change_request_url}")
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
    if summary.change_request_url is not None:
        typer.echo(f"change_request_url={summary.change_request_url}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


@dashboard_app.command("policy")
def dashboard_policy_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without updating dashboard policy state.",
    ),
) -> None:
    """Run the dedicated policy-processing workflow."""
    configure_logging()
    summary = dashboard_policy(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


def main() -> None:
    """Start the CLI application."""
    app()


if __name__ == "__main__":
    main()
