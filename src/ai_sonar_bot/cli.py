"""CLI entrypoint.

This module exposes the Typer application used to run the bot from the shell.
"""

from __future__ import annotations

import typer
from typer import Context

from ai_sonar_bot.logging import configure_logging
from ai_sonar_bot.runner import review, run

app = typer.Typer(add_completion=False, help="AI Sonar Bot CLI.")
review_app = typer.Typer(add_completion=False, help="Merge request review workflow.")
app.add_typer(review_app, name="review")


@app.command()
def run_command(
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without changing repository state."),
) -> None:
    """Run the bot.

    Args:
        dry_run: Whether to execute without publishing changes.
    """
    configure_logging()
    summary = run(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


@review_app.callback(invoke_without_command=True)
def review_command(
    ctx: Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Run without publishing a review note."),
) -> None:
    """Run the merge-request review workflow."""
    if ctx.invoked_subcommand is not None:
        return
    configure_logging()
    summary = review(dry_run=dry_run)
    typer.echo(f"run_id={summary.run_id}")
    typer.echo(f"status={summary.status.value}")
    typer.echo(summary.message)
    typer.echo(f"state_path={summary.state_path}")


def main() -> None:
    """Start the CLI application."""
    app()


if __name__ == "__main__":
    main()
