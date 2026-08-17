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
    recover_work_item,
    review,
    run_gitlab_issue_control_plane,
    run_remediation,
    sync_findings,
    sync_work_item_status,
)
from zeroone_ops.services.shared.run_state_service import RunSummary
from zeroone_ops.settings import SettingsError

app = typer.Typer(add_completion=False, help="ZeroOne Ops CLI.")
review_app = typer.Typer(add_completion=False, help="Merge request review workflow.")
dashboard_app = typer.Typer(add_completion=False, help="Dashboard sync workflows.")
findings_app = typer.Typer(add_completion=False, help="Finding ingestion workflows.")
remediation_app = typer.Typer(add_completion=False, help="Remediation workflows.")
work_items_app = typer.Typer(add_completion=False, help="Work-item lifecycle workflows.")
control_plane_app = typer.Typer(add_completion=False, help="Provider control-plane workflows.")
app.add_typer(review_app, name="review")
app.add_typer(dashboard_app, name="dashboard")
app.add_typer(findings_app, name="findings")
app.add_typer(remediation_app, name="remediation")
app.add_typer(work_items_app, name="work-items")
app.add_typer(control_plane_app, name="control-plane")


def _echo_review_summary(*, dry_run: bool) -> None:
    """Run the review workflow and print the CLI-facing summary."""
    configure_logging()
    _echo_summary(review(dry_run=dry_run))


def _echo_summary(summary: RunSummary) -> None:
    """Print one workflow summary in the CLI contract format."""
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    if summary.issue_key is not None:
        typer.echo(f"issue_key={summary.issue_key}")
    if summary.work_item_id is not None:
        typer.echo(f"work_item_id={summary.work_item_id}")
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


def _warn_deprecated_command(*, command: str, replacement: str) -> None:
    """Print one actionable warning for a legacy command alias."""
    typer.echo(
        "[warning] Deprecated command "
        f"`{command}` is a compatibility alias. Use `{replacement}` for new "
        "automation; it will be removed in a future major release.",
        err=True,
    )


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


@dashboard_app.command("sonar", deprecated=True)
def dashboard_sonar_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without updating the dashboard."),
) -> None:
    """Legacy GitLab alias for ``findings sync``."""
    configure_logging()
    _warn_deprecated_command(
        command="zeroone-ops dashboard sonar",
        replacement="zeroone-ops findings sync",
    )
    _echo_summary(sync_findings(dry_run=dry_run))


@findings_app.command("sync")
def findings_sync_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing findings."),
) -> None:
    """Sync normalized findings for the active platform."""
    configure_logging()
    _echo_summary(sync_findings(dry_run=dry_run))


@dashboard_app.command("remediate", deprecated=True)
def dashboard_remediate_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing remediation."),
) -> None:
    """Legacy GitLab alias for ``remediation run``."""
    configure_logging()
    _warn_deprecated_command(
        command="zeroone-ops dashboard remediate",
        replacement="zeroone-ops remediation run",
    )
    _echo_summary(run_remediation(dry_run=dry_run))


@remediation_app.command("run")
def remediation_run_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing remediation."),
) -> None:
    """Run remediation for the active platform."""
    configure_logging()
    _echo_summary(run_remediation(dry_run=dry_run))


@control_plane_app.command("run")
def control_plane_run_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without changing control-plane state.",
    ),
) -> None:
    """Run the combined GitLab issue-mode control plane."""
    configure_logging()
    _echo_summary(run_gitlab_issue_control_plane(dry_run=dry_run))


@work_items_app.command("sync-status")
def work_items_sync_status_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without updating work-item lifecycle state.",
    ),
) -> None:
    """Reconcile remediation work-item lifecycle status."""
    configure_logging()
    _echo_summary(sync_work_item_status(dry_run=dry_run))


@work_items_app.command("recover")
def work_items_recover_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Process recovery commands without updating work-item state.",
    ),
) -> None:
    """Process one recovery command from the current GitHub issue comment."""
    configure_logging()
    _echo_summary(recover_work_item(dry_run=dry_run))


@dashboard_app.command("reconcile", deprecated=True)
def dashboard_reconcile_command(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Run without updating dashboard lifecycle.",
    ),
) -> None:
    """Legacy GitLab alias for ``work-items sync-status``."""
    configure_logging()
    _warn_deprecated_command(
        command="zeroone-ops dashboard reconcile",
        replacement="zeroone-ops work-items sync-status",
    )
    _echo_summary(dashboard_reconcile(dry_run=dry_run))


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
    _echo_summary(dashboard_policy(dry_run=dry_run))


def main() -> None:
    """Start the CLI application."""
    try:
        app()
    except SettingsError as error:
        typer.echo(f"Configuration error: {error}", err=True)
        raise typer.Exit(code=2) from None


if __name__ == "__main__":
    main()
