from zeroone_ops.services.dashboard.dashboard_recovery_command_parser import (
    DashboardRecoveryCommandParser,
)


def test_parser_accepts_dashboard_item_recovery_commands() -> None:
    parser = DashboardRecoveryCommandParser()

    retry = parser.parse("/zeroone remediation sonar:AX-123 retry")
    dismiss = parser.parse("  /ZeroOne remediation ruff:C416 dismiss  ")

    assert retry.matched_prefix is True
    assert retry.item_id == "sonar:AX-123"
    assert retry.action == "retry"
    assert dismiss.matched_prefix is True
    assert dismiss.item_id == "ruff:C416"
    assert dismiss.action == "dismiss"


def test_parser_marks_invalid_prefixed_dashboard_commands_without_accepting_them() -> None:
    parser = DashboardRecoveryCommandParser()

    invalid = parser.parse("/zeroone remediation retry")
    unrelated = parser.parse("/zeroone policy severity enable high")

    assert invalid.matched_prefix is True
    assert invalid.item_id is None
    assert invalid.action is None
    assert unrelated.matched_prefix is False
    assert unrelated.item_id is None
    assert unrelated.action is None
