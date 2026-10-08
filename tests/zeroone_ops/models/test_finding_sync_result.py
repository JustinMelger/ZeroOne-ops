"""Contracts for shared finding-sync results and provider compatibility names."""

from dataclasses import FrozenInstanceError, asdict, fields

import pytest

from zeroone_ops.models.finding_sync import FindingSyncResult
from zeroone_ops.services.control_plane.work_items.github_finding_sync_service import (
    GitHubFindingSyncResult,
)
from zeroone_ops.services.control_plane.work_items.gitlab_finding_sync_service import (
    GitLabFindingSyncResult,
)

REQUIRED_FIELDS = (
    "promoted_count",
    "backlog_only_count",
    "created_count",
    "updated_count",
    "unchanged_count",
    "demoted_to_candidate_count",
    "retained_protected_count",
    "stale_demoted_to_candidate_count",
    "stale_retained_protected_count",
    "normalized_severity_counts",
    "enabled_severities",
    "backlog_reason_counts",
)
OPTIONAL_FIELDS = (
    "policy_deferred_count",
    "capacity_deferred_count",
    "policy_reactivated_count",
    "no_longer_detected_count",
    "projection_warning_count",
)


@pytest.mark.parametrize(
    "result_type", [FindingSyncResult, GitHubFindingSyncResult, GitLabFindingSyncResult]
)
def test_result_preserves_positional_arguments_defaults_and_serialization(
    result_type: type[FindingSyncResult],
) -> None:
    arguments = (1, 2, 1, 0, 0, 0, 1, 0, 1, {"high": 3}, ("high",), {"dismissed": 2})
    result = result_type(*arguments)

    expected = dict(zip(REQUIRED_FIELDS, arguments, strict=True))
    expected.update(dict.fromkeys(OPTIONAL_FIELDS, 0))
    assert asdict(result) == expected
    assert tuple(field.name for field in fields(result)) == REQUIRED_FIELDS + OPTIONAL_FIELDS
    assert isinstance(result, GitHubFindingSyncResult)
    assert isinstance(result, GitLabFindingSyncResult)
    with pytest.raises(FrozenInstanceError):
        result.promoted_count = 9  # type: ignore[misc]


def test_provider_names_are_aliases_for_one_shared_result() -> None:
    assert GitHubFindingSyncResult is FindingSyncResult
    assert GitLabFindingSyncResult is FindingSyncResult


def test_result_preserves_explicit_optional_counters() -> None:
    result = FindingSyncResult(
        promoted_count=1,
        backlog_only_count=2,
        created_count=1,
        updated_count=0,
        unchanged_count=0,
        demoted_to_candidate_count=0,
        retained_protected_count=0,
        stale_demoted_to_candidate_count=0,
        stale_retained_protected_count=0,
        normalized_severity_counts={"medium": 3},
        enabled_severities=("medium",),
        backlog_reason_counts={"promotion_capacity_exhausted": 2},
        policy_deferred_count=1,
        capacity_deferred_count=2,
        policy_reactivated_count=3,
        no_longer_detected_count=4,
        projection_warning_count=5,
    )

    assert [asdict(result)[name] for name in OPTIONAL_FIELDS] == [1, 2, 3, 4, 5]


def test_result_still_requires_existing_mandatory_arguments() -> None:
    with pytest.raises(TypeError, match="required positional"):
        FindingSyncResult()  # type: ignore[call-arg]
