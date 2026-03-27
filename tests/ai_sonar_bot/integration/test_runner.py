from ai_sonar_bot.runner import run


def test_run_dry_run_creates_summary() -> None:
    summary = run(dry_run=True)

    assert summary.status.value == "no_issue"
    assert "Dry run complete" in summary.message
