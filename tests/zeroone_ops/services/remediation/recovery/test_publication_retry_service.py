from zeroone_ops.models.change_request import ChangeRequestInfo
from zeroone_ops.models.work_item import PublicationRetryState
from zeroone_ops.services.remediation.change_request_publisher import (
    ChangeRequestPublishRequest,
    PublishedChangeRequest,
)
from zeroone_ops.services.remediation.recovery.publication_retry_service import (
    PublicationRetryService,
)


class StubBranchRevisionLookup:
    def __init__(self, sha: str | None) -> None:
        self.sha = sha
        self.requested_branch: str | None = None

    def get_branch_head_sha(self, *, branch_name: str) -> str | None:
        self.requested_branch = branch_name
        return self.sha


class StubChangeRequestPublisher:
    def __init__(self) -> None:
        self.request: ChangeRequestPublishRequest | None = None

    def publish(self, request: ChangeRequestPublishRequest) -> PublishedChangeRequest:
        self.request = request
        return PublishedChangeRequest(
            info=ChangeRequestInfo(
                iid=17,
                web_url="https://example.com/change_requests/17",
                title=request.title,
            ),
            action="reused",
        )


class FailingChangeRequestPublisher:
    def publish(self, request: ChangeRequestPublishRequest) -> PublishedChangeRequest:
        del request
        raise RuntimeError("provider publication failed")


def build_publication_retry() -> PublicationRetryState:
    return PublicationRetryState(
        branch_name="zeroone-ops/attempt-1",
        commit_sha="abc123",
        reason="change_request_publish_failed",
    )


def build_publish_request(
    *,
    source_branch: str = "zeroone-ops/attempt-1",
) -> ChangeRequestPublishRequest:
    return ChangeRequestPublishRequest(
        source_branch=source_branch,
        target_branch="main",
        title="fix: retry remediation",
        description="Retrying a verified branch publication.",
        labels=["zeroone-ops"],
    )


def test_retry_reuses_change_request_after_exact_branch_verification() -> None:
    lookup = StubBranchRevisionLookup("abc123")
    publisher = StubChangeRequestPublisher()
    service = PublicationRetryService(
        branch_revision_lookup=lookup,
        change_request_publisher=publisher,
    )

    result = service.retry(
        publication_retry=build_publication_retry(),
        request=build_publish_request(),
    )

    assert result.succeeded is True
    assert result.action == "reused"
    assert lookup.requested_branch == "zeroone-ops/attempt-1"
    assert publisher.request is not None


def test_retry_does_not_publish_when_recorded_branch_is_missing() -> None:
    publisher = StubChangeRequestPublisher()
    service = PublicationRetryService(
        branch_revision_lookup=StubBranchRevisionLookup(None),
        change_request_publisher=publisher,
    )

    result = service.retry(
        publication_retry=build_publication_retry(),
        request=build_publish_request(),
    )

    assert result.succeeded is False
    assert result.error_message == "Recorded remediation branch no longer exists remotely."
    assert publisher.request is None


def test_retry_does_not_publish_when_recorded_commit_changed() -> None:
    publisher = StubChangeRequestPublisher()
    service = PublicationRetryService(
        branch_revision_lookup=StubBranchRevisionLookup("changed"),
        change_request_publisher=publisher,
    )

    result = service.retry(
        publication_retry=build_publication_retry(),
        request=build_publish_request(),
    )

    assert result.succeeded is False
    assert result.error_message == (
        "Recorded remediation branch no longer matches its published commit."
    )
    assert publisher.request is None


def test_retry_does_not_publish_when_request_branch_differs_from_recorded_branch() -> None:
    publisher = StubChangeRequestPublisher()
    service = PublicationRetryService(
        branch_revision_lookup=StubBranchRevisionLookup("abc123"),
        change_request_publisher=publisher,
    )

    result = service.retry(
        publication_retry=build_publication_retry(),
        request=build_publish_request(source_branch="zeroone-ops/other"),
    )

    assert result.succeeded is False
    assert result.error_message == (
        "Publication retry source branch did not match the recorded branch."
    )
    assert publisher.request is None


def test_retry_returns_publish_failure_without_leaking_provider_error() -> None:
    service = PublicationRetryService(
        branch_revision_lookup=StubBranchRevisionLookup("abc123"),
        change_request_publisher=FailingChangeRequestPublisher(),
    )

    result = service.retry(
        publication_retry=build_publication_retry(),
        request=build_publish_request(),
    )

    assert result.succeeded is False
    assert result.error_message == (
        "Recorded branch publication retry failed: provider publication failed"
    )
