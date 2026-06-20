import json
from typing import cast

from zeroone_ops.models.gitlab import GitLabMergeRequestState, MergeRequestNote
from zeroone_ops.models.review import (
    ChangeRequestDiffRefs,
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    ReviewClassification,
    ReviewFileContext,
)
from zeroone_ops.providers.review.platform import ReviewPlatformClientError


def extract_machine_safe_payload(body: str) -> dict[str, object]:
    start_marker = "<!-- ai-sonar-bot:review-note:v1\n"
    end_marker = "\n-->"
    start = body.index(start_marker) + len(start_marker)
    end = body.index(end_marker, start)
    return cast(dict[str, object], json.loads(body[start:end]))


def build_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base123",
            start_sha="start123",
            head_sha="abc123",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_multiline_context() -> ChangeRequestReviewContext:
    return ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        diff_refs=ChangeRequestDiffRefs(
            base_sha="base123",
            start_sha="start123",
            head_sha="abc123",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -73,3 +73,3 @@",
                start_line=73,
                end_line=75,
                content=(
                    "  73: raw_vehicle_id = vehicle.get('vehicle_id')\n"
                    "  74: normalized_vehicle_id = raw_vehicle_id.strip()\n"
                    "  75: return lookup_articles(normalized_vehicle_id)\n"
                ),
                full_file_included=True,
                truncated=False,
            )
        ],
    )


def build_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_clear_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "clear123",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="no_findings",
                        findings_count=0,
                        summary="No actionable findings in the earlier pass.",
                        findings=[],
                    )
                ],
            ),
        }
    )


def build_manual_review_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "manual123",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="manual_review_only",
                        findings_count=0,
                        summary="The earlier pass could not assess the diff reliably.",
                        findings=[],
                    )
                ],
            ),
        }
    )


def build_ambiguous_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=1,
                        summary="One earlier concern still needs attention.",
                        findings=[
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            )
                        ],
                    )
                ],
            ),
        }
    )


def build_mixed_ambiguity_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "def456",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="abc123",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity="src/service.py::coverage-miss-test",
                                summary="src/service.py: Missing test coverage",
                                severity="medium",
                            ),
                            PriorReviewFinding(
                                summary="Earlier concern around helper behavior",
                                severity="medium",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


def build_variant_title_follow_up_context() -> ChangeRequestReviewContext:
    return build_context().model_copy(
        update={
            "head_sha": "ghi789",
            "prior_review_context": PriorReviewContext(
                change_request_number=17,
                passes=[
                    PriorReviewPass(
                        reviewed_head_sha="def456",
                        classification="findings_present",
                        findings_count=2,
                        summary="Two earlier concerns still need attention.",
                        findings=[
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_articles_functions.py::"
                                    "cylinder-except-fail-helper-lookup-unconditional"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_articles_functions.py: "
                                    "Unconditional exception breaks cylinder lookup helper"
                                ),
                                severity="high",
                            ),
                            PriorReviewFinding(
                                identity=(
                                    "bnl_app/functions/vehicle_functions.py::"
                                    "detail-except-fail-lookup-unconditional-vehicle"
                                ),
                                summary=(
                                    "bnl_app/functions/vehicle_functions.py: "
                                    "Unconditional exception breaks vehicle detail retrieval"
                                ),
                                severity="high",
                            ),
                        ],
                    )
                ],
            ),
        }
    )


class FakeGitLabReviewClient:
    def __init__(self) -> None:
        self.published_body: str | None = None
        self.inline_comments: list[tuple[str, int]] = []
        self.updated_body: str | None = None
        self.fail_inline_publish = False
        self.fail_note_update = False

    def create_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid
        self.published_body = body
        return MergeRequestNote(
            id=55,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        )

    def create_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
    ) -> MergeRequestNote:
        return self.create_merge_request_note(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            body=body,
        )

    def list_open_merge_requests(self, *, project_id: str) -> list[ChangeRequestReviewCandidate]:
        del project_id
        raise NotImplementedError

    def get_merge_request(
        self, *, project_id: str, merge_request_iid: int
    ) -> ChangeRequestReviewCandidate:
        del project_id, merge_request_iid
        raise NotImplementedError

    def get_merge_request_state(
        self, *, project_id: str, merge_request_iid: int
    ) -> GitLabMergeRequestState:
        del project_id, merge_request_iid
        raise NotImplementedError

    def list_merge_request_notes(
        self, *, project_id: str, merge_request_iid: int
    ) -> list[MergeRequestNote]:
        del project_id, merge_request_iid
        raise NotImplementedError

    def get_current_user_username(self) -> str:
        return "zeroone-ops"

    def update_merge_request_note(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid, note_id
        if self.fail_note_update:
            raise ReviewPlatformClientError("update failed")
        self.updated_body = body
        return MergeRequestNote(
            id=55,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
        )

    def update_change_request_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        note_id: int,
        body: str,
    ) -> MergeRequestNote:
        return self.update_merge_request_note(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            note_id=note_id,
            body=body,
        )

    def create_merge_request_inline_comment(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        del project_id, merge_request_iid, base_sha, start_sha, head_sha, old_path, new_path
        if self.fail_inline_publish:
            raise ReviewPlatformClientError("inline failed")
        self.inline_comments.append((body, new_line))
        return MergeRequestNote(
            id=789,
            web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_789",
        )

    def create_change_request_inline_comment(
        self,
        *,
        repository_id: str,
        change_request_number: int,
        body: str,
        base_sha: str,
        start_sha: str,
        head_sha: str,
        old_path: str,
        new_path: str,
        new_line: int,
    ) -> MergeRequestNote:
        return self.create_merge_request_inline_comment(
            project_id=repository_id,
            merge_request_iid=change_request_number,
            body=body,
            base_sha=base_sha,
            start_sha=start_sha,
            head_sha=head_sha,
            old_path=old_path,
            new_path=new_path,
            new_line=new_line,
        )


def build_artifact(
    *,
    classification: ReviewClassification = "findings_present",
    summary: str | None = None,
    follow_up_lines: list[str] | None = None,
    advisory_notes: list[str] | None = None,
) -> PublishableReviewArtifact:
    findings = (
        []
        if classification != "findings_present"
        else [
            PublishableReviewFinding(
                severity="medium",
                file_path="src/service.py",
                line_start=1,
                line_end=1,
                stable_identity="src/service.py::coverage-miss-test",
                legacy_identity="src/service.py::coverage-miss-test",
                title="Missing test coverage",
                evidence="The diff changes `value = 1` to `value = 2` without any test updates.",
                explanation="The change alters branch behavior without test updates.",
                suggested_follow_up="Add a regression test for the changed branch.",
            )
        ]
    )
    artifact_summary = summary
    if artifact_summary is None:
        artifact_summary = {
            "findings_present": "One medium-risk finding.",
            "no_findings": "No actionable findings in this review pass.",
            "manual_review_only": "The diff is too broad to assess reliably in this pass.",
        }[classification]
    return PublishableReviewArtifact(
        classification=classification,
        summary=artifact_summary,
        review_confidence=0.82 if classification == "findings_present" else 0.91,
        review_confidence_reason=(
            "The diff is small and the evidence is specific."
            if classification == "findings_present"
            else "The reviewed change is narrow and well supported."
        ),
        findings=findings,
        advisory_notes=advisory_notes or [],
        follow_up_lines=follow_up_lines or [],
    )
