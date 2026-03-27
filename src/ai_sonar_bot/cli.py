"""CLI entrypoint.

This module exposes the Typer application used to run the bot from the shell.
"""

from __future__ import annotations

import typer

from ai_sonar_bot.logging import configure_logging
from ai_sonar_bot.runner import run

app = typer.Typer(add_completion=False, help="AI Sonar Bot CLI.")


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


def main() -> None:
    """Start the CLI application."""
    app()


if __name__ == "__main__":
    main()
