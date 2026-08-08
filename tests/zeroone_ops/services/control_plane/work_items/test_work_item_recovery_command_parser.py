from zeroone_ops.services.control_plane.work_items.work_item_recovery_command_parser import (
    WorkItemRecoveryCommandParser,
)


def test_parser_accepts_standalone_recovery_commands() -> None:
    parser = WorkItemRecoveryCommandParser()

    requeue = parser.parse("/zeroone remediation requeue")
    dismiss = parser.parse("  /ZeroOne remediation dismiss  ")

    assert requeue.matched_prefix is True
    assert requeue.action == "requeue"
    assert dismiss.matched_prefix is True
    assert dismiss.action == "dismiss"


def test_parser_marks_invalid_prefixed_commands_without_accepting_them() -> None:
    parser = WorkItemRecoveryCommandParser()

    invalid = parser.parse("/zeroone remediation reopen")
    legacy = parser.parse("/zeroone remediation retry")
    unrelated = parser.parse("/zeroone policy severity enable high")

    assert invalid.matched_prefix is True
    assert invalid.action is None
    assert legacy.matched_prefix is True
    assert legacy.action is None
    assert unrelated.matched_prefix is False
    assert unrelated.action is None
