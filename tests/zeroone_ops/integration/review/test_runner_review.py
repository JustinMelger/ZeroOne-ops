from collections.abc import Callable
from pathlib import Path

from zeroone_ops.models.dashboard import (
    DashboardDocument,
    DashboardItem,
    DashboardSection,
    empty_sections,
)
from zeroone_ops.models.gitlab import MergeRequestNote
from zeroone_ops.models.review import (
    CandidateReviewFinding,
    CandidateReviewResult,
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    PriorReviewFinding,
    PriorReviewPass,
    PublishableReviewArtifact,
    PublishableReviewFinding,
    RemediationReviewContext,
    ReviewComment,
    ReviewFileContext,
    ReviewFinding,
    ReviewResult,
)
from zeroone_ops.models.state import (
    AppState,
    ChangeRequestReviewState,
    RepositoryState,
)
from zeroone_ops.runner import (
    review,
)
from zeroone_ops.services.review.context.review_context_builder import (
    ReviewContextBuildResult,
)
from zeroone_ops.services.review.continuity.review_overlap_analysis_service import (
    ReviewOverlapAnalysisResult,
)
from zeroone_ops.services.review.publish.review_publisher import ReviewPublishResult
from zeroone_ops.services.shared.state_store import StateStore


class _SelectionResult:
    def __init__(
        self,
        *,
        selected_change_request: ChangeRequestReviewCandidate | None,
        change_request_count: int,
        message: str,
    ) -> None:
        self.selected_change_request = selected_change_request
        self.change_request_count = change_request_count
        self.message = message


class _CandidateStageResult:
    def __init__(
        self,
        *,
        candidate_result: CandidateReviewResult | None,
        raw_review_result: ReviewResult,
        forwarded_candidate_ids: tuple[str, ...],
        pre_precision_dropped_candidates: tuple[str, ...],
        candidate_annotations: tuple[object, ...],
        message: str,
    ) -> None:
        self.candidate_result = candidate_result
        self.raw_review_result = raw_review_result
        self.forwarded_candidate_ids = forwarded_candidate_ids
        self.pre_precision_dropped_candidates = pre_precision_dropped_candidates
        self.candidate_annotations = candidate_annotations
        self.message = message


class _DashboardUpdateResult:
    def __init__(
        self,
        *,
        dashboard_issue_url: str | None,
        error_message: str | None,
    ) -> None:
        self.dashboard_issue_url = dashboard_issue_url
        self.error_message = error_message


class _PriorNoteSelectionResult:
    def __init__(
        self,
        *,
        selected_note: ReviewComment | MergeRequestNote | None,
        considered_note_count: int,
        author_matched_note_count: int,
        machine_safe_note_count: int,
        parseable_note_count: int,
        current_sha_skipped_count: int,
        reason_code: str,
        message: str,
    ) -> None:
        self.selected_note = selected_note
        self.considered_note_count = considered_note_count
        self.author_matched_note_count = author_matched_note_count
        self.machine_safe_note_count = machine_safe_note_count
        self.parseable_note_count = parseable_note_count
        self.current_sha_skipped_count = current_sha_skipped_count
        self.reason_code = reason_code
        self.message = message


class _ParseNoteResult:
    def __init__(self, *, prior_review_pass: PriorReviewPass | None, message: str) -> None:
        self.prior_review_pass = prior_review_pass
        self.message = message


class _ProjectionResult:
    def __init__(self, *, action: str) -> None:
        self.action = action


def build_dashboard_document(*, items: list[DashboardItem]) -> DashboardDocument:
    sections = empty_sections()
    sections[0] = DashboardSection(
        key="open_candidates",
        title="Open Candidates",
        items=items,
    )
    return DashboardDocument(
        issue_id=10,
        issue_iid=11,
        issue_url="https://gitlab.example.com/group/project/-/issues/11",
        title="AI Code Ops Work Queue",
        sections=sections,
    )


class _IntegrationPrecisionClient:
    def review_precision_reconciliation(
        self,
        context: ChangeRequestReviewContext,
        *,
        candidates: list[CandidateReviewFinding],
        candidate_annotations,
        overlap_packet,
        candidate_stage_summary: str,
        candidate_stage_classification: str,
        candidate_stage_rationale: str,
        max_findings: int,
    ) -> PrecisionReviewDecision:
        del context, candidate_annotations, overlap_packet, max_findings
        if candidate_stage_classification == "manual_review_only":
            return PrecisionReviewDecision(
                review_classification="manual_review_only",
                decision_summary=candidate_stage_summary,
                decision_rationale=candidate_stage_rationale,
                accepted_findings=[],
                dropped_candidates=[],
            )
        if not candidates:
            return PrecisionReviewDecision(
                review_classification="no_findings",
                decision_summary="No actionable findings after review validation.",
                decision_rationale=candidate_stage_rationale,
                accepted_findings=[],
                dropped_candidates=[],
            )
        return PrecisionReviewDecision(
            review_classification="findings_present",
            decision_summary=candidate_stage_summary,
            decision_rationale=candidate_stage_rationale,
            accepted_findings=[
                PrecisionAcceptedFinding(
                    source_candidate_ids=[candidate.candidate_id],
                    severity=candidate.severity,
                    file_path=candidate.file_path,
                    line_start=candidate.line_start,
                    line_end=candidate.line_end,
                    symbol=candidate.symbol,
                    issue_kind=candidate.issue_kind,
                    region_hint=candidate.region_hint,
                    title=candidate.title,
                    summary=candidate.title,
                    evidence=[candidate.evidence],
                    why_it_matters=candidate.explanation,
                    recommended_follow_up=candidate.suggested_follow_up,
                )
                for candidate in candidates
            ],
            dropped_candidates=[],
        )


def _install_review_precision_fake(monkeypatch) -> None:
    def _build_precision_client(self: object) -> _IntegrationPrecisionClient:
        del self
        return _IntegrationPrecisionClient()

    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_reconciliation_service."
        "ReviewReconciliationService._build_llm_client",
        _build_precision_client,
    )


def _stub_select_change_request(
    change_request: ChangeRequestReviewCandidate | None,
    *,
    change_request_count: int = 1,
    message: str = "",
) -> Callable[[object, AppState, str, int | None, str | None], _SelectionResult]:
    def _select(
        self: object,
        state: AppState,
        repository_id: str,
        change_request_number: int | None,
        triggered_head_sha: str | None = None,
    ) -> _SelectionResult:
        del self, state, repository_id, change_request_number, triggered_head_sha
        return _SelectionResult(
            selected_change_request=change_request,
            change_request_count=change_request_count,
            message=message,
        )

    return _select


def _stub_build_context(
    context: ChangeRequestReviewContext,
) -> Callable[[object, ChangeRequestReviewCandidate], ReviewContextBuildResult]:
    def _build(
        self: object,
        change_request: ChangeRequestReviewCandidate,
    ) -> ReviewContextBuildResult:
        del self, change_request
        return ReviewContextBuildResult(context=context, message="")

    return _build


def _stub_candidate_stage(
    *,
    candidate_result: CandidateReviewResult | None,
    raw_review_result: ReviewResult,
    forwarded_candidate_ids: tuple[str, ...] = (),
    pre_precision_dropped_candidates: tuple[str, ...] = (),
    candidate_annotations: tuple[object, ...] = (),
    message: str,
) -> Callable[[object, ChangeRequestReviewContext], _CandidateStageResult]:
    def _analyze(
        self: object,
        context: ChangeRequestReviewContext,
    ) -> _CandidateStageResult:
        del self, context
        return _CandidateStageResult(
            candidate_result=candidate_result,
            raw_review_result=raw_review_result,
            forwarded_candidate_ids=forwarded_candidate_ids,
            pre_precision_dropped_candidates=pre_precision_dropped_candidates,
            candidate_annotations=candidate_annotations,
            message=message,
        )

    return _analyze


def _stub_dashboard_update(
    *,
    dashboard_issue_url: str | None,
    error_message: str | None,
) -> Callable[[object, str, ChangeRequestReviewCandidate, ReviewResult], _DashboardUpdateResult]:
    def _update(
        self: object,
        project_id: str,
        merge_request: ChangeRequestReviewCandidate,
        review_result: ReviewResult,
    ) -> _DashboardUpdateResult:
        del self, project_id, merge_request, review_result
        return _DashboardUpdateResult(
            dashboard_issue_url=dashboard_issue_url,
            error_message=error_message,
        )

    return _update


def _stub_get_change_request(
    change_request: ChangeRequestReviewCandidate,
) -> Callable[[object, str, int], ChangeRequestReviewCandidate]:
    def _get(
        self: object,
        repository_id: str,
        change_request_number: int,
    ) -> ChangeRequestReviewCandidate:
        del self, repository_id, change_request_number
        return change_request

    return _get


def _stub_get_current_username(
    username: str,
) -> Callable[[object], str]:
    def _get(self: object) -> str:
        del self
        return username

    return _get


def _stub_raise_runtime_error(
    message: str,
) -> Callable[[object], str]:
    def _raise(self: object) -> str:
        del self
        raise RuntimeError(message)

    return _raise


def _stub_list_comments(
    comments: list[ReviewComment],
) -> Callable[[object, str, int], list[ReviewComment]]:
    def _list(self: object, repository_id: str, change_request_number: int) -> list[ReviewComment]:
        del self, repository_id, change_request_number
        return comments

    return _list


def _stub_list_merge_request_notes(
    notes: list[MergeRequestNote],
) -> Callable[[object, str, int], list[MergeRequestNote]]:
    def _list(self: object, project_id: str, merge_request_iid: int) -> list[MergeRequestNote]:
        del self, project_id, merge_request_iid
        return notes

    return _list


def _stub_get_gitlab_merge_request(
    change_request: ChangeRequestReviewCandidate,
) -> Callable[[object, str, int], ChangeRequestReviewCandidate]:
    def _get(
        self: object,
        project_id: str,
        merge_request_iid: int,
    ) -> ChangeRequestReviewCandidate:
        del self, project_id, merge_request_iid
        return change_request

    return _get


def _stub_select_latest_prior_review_note(
    *,
    selected_note: ReviewComment | MergeRequestNote | None,
    considered_note_count: int,
    author_matched_note_count: int,
    machine_safe_note_count: int,
    parseable_note_count: int,
    current_sha_skipped_count: int,
    reason_code: str,
    message: str,
) -> Callable[[object, str, int, str], _PriorNoteSelectionResult]:
    def _select(
        self: object,
        repository_id: str,
        change_request_number: int,
        current_head_sha: str,
    ) -> _PriorNoteSelectionResult:
        del self, repository_id, change_request_number, current_head_sha
        return _PriorNoteSelectionResult(
            selected_note=selected_note,
            considered_note_count=considered_note_count,
            author_matched_note_count=author_matched_note_count,
            machine_safe_note_count=machine_safe_note_count,
            parseable_note_count=parseable_note_count,
            current_sha_skipped_count=current_sha_skipped_count,
            reason_code=reason_code,
            message=message,
        )

    return _select


def _stub_parse_prior_note(
    prior_review_pass: PriorReviewPass | None,
    *,
    message: str,
) -> Callable[[object, ReviewComment | MergeRequestNote, int], _ParseNoteResult]:
    def _parse(
        self: object,
        note: ReviewComment | MergeRequestNote,
        expected_change_request_number: int,
    ) -> _ParseNoteResult:
        del self, note, expected_change_request_number
        return _ParseNoteResult(
            prior_review_pass=prior_review_pass,
            message=message,
        )

    return _parse


def _stub_overlap_analysis(
    result: ReviewOverlapAnalysisResult,
) -> Callable[[object, object], ReviewOverlapAnalysisResult]:
    def _analyze(self: object, packet: object) -> ReviewOverlapAnalysisResult:
        del self, packet
        return result

    return _analyze


def test_review_dry_run_creates_review_summary(tmp_path: Path, monkeypatch) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=None,
            raw_review_result=ReviewResult(
                classification="no_findings",
                summary="No findings.",
                findings=[],
            ),
            message="Candidate review generated 0 candidates and accepted 0 findings.",
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "Reviewed change request #17 at abc123." in summary.message
    assert "Dry-run skipped note publication." in summary.message


def test_review_github_non_dry_run_publishes_summary_comment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    event_path = tmp_path / "github-event.json"
    event_path.write_text('{"pull_request": {"number": 23}}', encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "review": {
            "platform": "github"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    change_request = ChangeRequestReviewCandidate(
        change_request_number=23,
        title="feat: github review flow",
        description="summary",
        source_branch="feature/github-review",
        target_branch="main",
        web_url="https://github.com/octo-org/octo-repo/pull/23",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=23,
        title="feat: github review flow",
        description="summary",
        source_branch="feature/github-review",
        target_branch="main",
        web_url="https://github.com/octo-org/octo-repo/pull/23",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(change_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=None,
            raw_review_result=ReviewResult(
                classification="no_findings",
                summary="No findings.",
                findings=[],
            ),
            message="Candidate review generated 0 candidates and accepted 0 findings.",
        ),
    )

    observed: dict[str, object] = {}

    def capture_publish(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, context, inline_comment_decisions
        observed["repository_id"] = repository_id
        observed["change_request_number"] = change_request_number
        observed["artifact"] = artifact
        return ReviewPublishResult(
            note=type(
                "Note",
                (),
                {
                    "id": 88,
                    "web_url": "https://github.com/octo-org/octo-repo/pull/23#issuecomment-88",
                },
            )(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        capture_publish,
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert observed["repository_id"] == "octo-org/octo-repo"
    assert observed["change_request_number"] == 23
    assert observed["artifact"].classification == "no_findings"
    assert "Review note: https://github.com/octo-org/octo-repo/pull/23#issuecomment-88" in (
        summary.message
    )
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id=None,
        sonarqube_project_key=None,
    ).load()
    assert state.reviews["23:abc123"].change_request_number == 23


def test_review_github_stops_when_live_head_sha_differs_from_triggered_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    event_path = tmp_path / "github-event.json"
    event_path.write_text(
        '{"pull_request": {"number": 23, "head": {"sha": "oldsha123"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "review": {
            "platform": "github"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.review.github.GitHubReviewClient.get_change_request",
        _stub_get_change_request(
            ChangeRequestReviewCandidate(
                change_request_number=23,
                title="feat: github review flow",
                description="summary",
                source_branch="feature/github-review",
                target_branch="main",
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                head_sha="newsha456",
                changes=[],
            )
        ),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "failed"
    assert "live change request head SHA no longer matches" in summary.message
    assert "oldsha123 -> newsha456" in summary.message


def test_review_non_dry_run_publishes_findings_and_persists_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=CandidateReviewResult(
                findings=[
                    CandidateReviewFinding(
                        candidate_id="candidate-1",
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ]
            ),
            raw_review_result=ReviewResult(
                classification="findings_present",
                summary="One medium-risk finding.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ],
            ),
            forwarded_candidate_ids=("candidate-1",),
            message=(
                "Candidate review generated 1 candidates and forwarded 1 findings to precision."
            ),
        ),
    )

    def publish_artifact_stub(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, repository_id, change_request_number, context, inline_comment_decisions
        return ReviewPublishResult(
            note=type(
                "Note",
                (),
                {
                    "id": 55,
                    "web_url": (
                        "https://gitlab.example.com/group/project/-/merge_requests/17#note_55"
                    ),
                },
            )(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        publish_artifact_stub,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_dashboard_updater.ReviewDashboardUpdater.update",
        _stub_dashboard_update(
            dashboard_issue_url="https://gitlab.example.com/group/project/-/issues/11",
            error_message=None,
        ),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "Reviewed change request #17 at abc123." in summary.message
    assert (
        "Review note: https://gitlab.example.com/group/project/-/merge_requests/17#note_55"
        in summary.message
    )
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    assert state.reviews["17:abc123"].status == "findings_present"
    assert state.runs[-1].review_diagnostics is not None
    diagnostics = state.runs[-1].review_diagnostics
    assert diagnostics.reviewed_head_sha == "abc123"
    assert diagnostics.candidate_findings[0].candidate_id == "candidate-1"
    assert diagnostics.forwarded_candidate_ids == ["candidate-1"]
    assert diagnostics.precision_accepted_candidate_ids == ["candidate-1"]
    assert diagnostics.inline_comment_decisions == []
    assert diagnostics.final_published_finding_summaries == [
        "src/service.py: Missing test coverage"
    ]
    assert diagnostics.final_classification == "findings_present"


def test_review_non_dry_run_succeeds_when_dashboard_mirror_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=None,
            raw_review_result=ReviewResult(
                classification="no_findings",
                summary="No findings.",
                findings=[],
            ),
            message="Candidate review generated 0 candidates and accepted 0 findings.",
        ),
    )

    def publish_artifact_stub(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, repository_id, change_request_number, context, inline_comment_decisions
        return ReviewPublishResult(
            note=type("Note", (), {"id": 55, "web_url": None})(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        publish_artifact_stub,
    )
    observed: dict[str, object] = {}

    def capture_dashboard_update(  # noqa: ANN001, ANN202
        self,
        project_id,
        merge_request,
        review_result,
    ):
        del self, project_id, merge_request
        observed["dashboard_review_result"] = review_result
        return type(
            "DashboardResult",
            (),
            {
                "dashboard_issue_url": None,
                "error_message": "Dashboard mirror failed: boom",
            },
        )()

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_dashboard_updater.ReviewDashboardUpdater.update",
        capture_dashboard_update,
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "Dashboard mirror failed: boom" in summary.message
    dashboard_review_result = observed["dashboard_review_result"]
    assert isinstance(dashboard_review_result, ReviewResult)
    assert dashboard_review_result.summary == "No actionable findings in this review pass."
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    assert state.reviews["17:abc123"].summary == "No actionable findings in this review pass."
    assert state.runs[-1].review_diagnostics is not None
    diagnostics = state.runs[-1].review_diagnostics
    assert diagnostics.reviewed_head_sha == "abc123"
    assert diagnostics.candidate_findings == []
    assert diagnostics.forwarded_candidate_ids == []
    assert diagnostics.precision_accepted_candidate_ids == []
    assert diagnostics.inline_comment_decisions == []
    assert diagnostics.final_published_finding_summaries == []
    assert diagnostics.final_classification == "no_findings"


def test_review_non_dry_run_downgrades_structurally_invalid_artifact_to_manual_review_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=CandidateReviewResult(
                findings=[
                    CandidateReviewFinding(
                        candidate_id="candidate-1",
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ]
            ),
            raw_review_result=ReviewResult(
                classification="findings_present",
                summary="No actionable findings in this review pass.",
                review_confidence_reason="The regression is visible in the diff.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ],
            ),
            forwarded_candidate_ids=("candidate-1",),
            message=(
                "Candidate review generated 1 candidates and forwarded 1 findings to precision."
            ),
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_artifact_builder.ReviewArtifactBuilder.build",
        lambda self, **kwargs: type(
            "BuildResult",
            (),
            {
                "artifact": PublishableReviewArtifact(
                    classification="no_findings",
                    summary="No actionable findings in this review pass.",
                    findings=[
                        PublishableReviewFinding(
                            severity="medium",
                            file_path="src/service.py",
                            title="Missing test coverage",
                            evidence=(
                                "The diff changes `value = 1` to `value = 2` "
                                "without any test updates."
                            ),
                            explanation="The change alters behavior without test updates.",
                            suggested_follow_up="Add a regression test.",
                        )
                    ],
                ),
                "message": "Built publishable review artifact with contradictory shape.",
            },
        )(),
    )

    observed: dict[str, object] = {}

    def capture_publish(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, repository_id, change_request_number, context
        observed["artifact"] = artifact
        observed["inline_comment_decisions"] = inline_comment_decisions
        return ReviewPublishResult(
            note=type("Note", (), {"id": 55, "web_url": None})(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        capture_publish,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_dashboard_updater.ReviewDashboardUpdater.update",
        _stub_dashboard_update(
            dashboard_issue_url=None,
            error_message=None,
        ),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    artifact = observed["artifact"]
    assert artifact.classification == "manual_review_only"
    state = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    ).load()
    assert state.reviews["17:abc123"].status == "manual_review_only"


def test_review_non_dry_run_omits_continuity_when_overlap_analysis_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="def456",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="def456",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    selected_note = type(
        "Note",
        (),
        {
            "id": 44,
            "web_url": "https://gitlab.example.com/group/project/-/merge_requests/17#note_44",
            "body": "machine-safe",
            "author_username": "ai-sonar-bot",
            "created_at": "2026-04-19T11:27:42.046Z",
        },
    )()
    monkeypatch.setattr(
        "zeroone_ops.services.review.continuity.review_prior_comment_loader.ChangeRequestPriorCommentLoader.select_latest_prior_review_note",
        _stub_select_latest_prior_review_note(
            selected_note=selected_note,
            considered_note_count=2,
            author_matched_note_count=1,
            machine_safe_note_count=1,
            parseable_note_count=1,
            current_sha_skipped_count=0,
            reason_code="selected",
            message="Selected latest earlier machine-safe bot review note.",
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.continuity.review_prior_comment_parser.ChangeRequestPriorCommentParser.parse_note",
        _stub_parse_prior_note(
            PriorReviewPass(
                reviewed_head_sha="abc123",
                classification="findings_present",
                findings_count=1,
                summary="One earlier concern still needs attention.",
                note_url=selected_note.web_url,
                findings=[
                    PriorReviewFinding(
                        identity="src/service.py::missing-test-coverage",
                        legacy_identity="src/service.py::coverage-miss-test",
                        summary="src/service.py: Missing test coverage",
                        severity="medium",
                        symbol=None,
                        issue_kind=None,
                        region_hint=None,
                    )
                ],
            ),
            message="Parsed machine-safe prior review note successfully.",
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=CandidateReviewResult(
                findings=[
                    CandidateReviewFinding(
                        candidate_id="candidate-1",
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ]
            ),
            raw_review_result=ReviewResult(
                classification="findings_present",
                summary="One medium-risk finding.",
                findings=[
                    ReviewFinding(
                        severity="medium",
                        file_path="src/service.py",
                        title="Missing test coverage",
                        evidence=(
                            "The diff changes `value = 1` to `value = 2` without any test updates."
                        ),
                        explanation="The change alters behavior without test updates.",
                        suggested_follow_up="Add a regression test.",
                    )
                ],
            ),
            forwarded_candidate_ids=("candidate-1",),
            message=(
                "Candidate review generated 1 candidates and forwarded 1 findings to precision."
            ),
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.continuity.review_overlap_analysis_service.ReviewOverlapAnalysisService.analyze",
        _stub_overlap_analysis(
            ReviewOverlapAnalysisResult(
                overlap_result=None,
                status="llm_error",
                message="Structured review overlap reconciliation failed.",
            )
        ),
    )

    observed: dict[str, object] = {}

    def capture_publish(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, repository_id, change_request_number, context
        observed["artifact"] = artifact
        observed["inline_comment_decisions"] = inline_comment_decisions
        return ReviewPublishResult(
            note=type(
                "Note",
                (),
                {
                    "id": 55,
                    "web_url": (
                        "https://gitlab.example.com/group/project/-/merge_requests/17#note_55"
                    ),
                },
            )(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        capture_publish,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_dashboard_updater.ReviewDashboardUpdater.update",
        _stub_dashboard_update(
            dashboard_issue_url=None,
            error_message=None,
        ),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert observed["artifact"].follow_up_lines == []
    assert "Reviewed change request #17 at def456." in summary.message


def test_review_non_dry_run_publishes_no_findings_note_for_continuity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=None,
            raw_review_result=ReviewResult(
                classification="no_findings",
                summary="No findings.",
                findings=[],
            ),
            message="Candidate review generated 0 candidates and accepted 0 findings.",
        ),
    )

    observed: dict[str, object] = {}

    def capture_publish(  # noqa: ANN001, ANN202
        self,
        repository_id,
        change_request_number,
        context,
        artifact,
        inline_comment_decisions=None,
    ):
        del self, repository_id, change_request_number, context
        observed["artifact"] = artifact
        observed["inline_comment_decisions"] = inline_comment_decisions
        return ReviewPublishResult(
            note=type(
                "Note",
                (),
                {
                    "id": 77,
                    "web_url": (
                        "https://gitlab.example.com/group/project/-/merge_requests/17#note_77"
                    ),
                },
            )(),
            body="summary",
            artifact=artifact,
        )

    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_publisher.ReviewPublisher.publish_artifact",
        capture_publish,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.publish.review_dashboard_updater.ReviewDashboardUpdater.update",
        _stub_dashboard_update(
            dashboard_issue_url=None,
            error_message=None,
        ),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "Reviewed change request #17 at abc123." in summary.message
    assert observed["artifact"].classification == "no_findings"
    assert observed["artifact"].summary == "No actionable findings in this review pass."
    assert observed["artifact"].follow_up_lines == []
    assert "Review note:" in summary.message


def test_review_skips_unchanged_sha_revision_integration(tmp_path: Path, monkeypatch) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    state = AppState(repository=RepositoryState(base_branch="main"))
    state.reviews["17:abc123"] = ChangeRequestReviewState(
        change_request_number=17,
        head_sha="abc123",
        status="no_findings",
        last_run_id="run-1",
    )
    store.save(state)

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request",
        _stub_get_gitlab_merge_request(
            ChangeRequestReviewCandidate(
                change_request_number=17,
                title="feat: review flow",
                description="summary",
                source_branch="feature/review",
                target_branch="main",
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                head_sha="abc123",
                changes=[],
            )
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Earlier classification: no_findings." in summary.message


def test_review_skips_unchanged_sha_revision_via_gitlab_note_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request",
        _stub_get_gitlab_merge_request(
            ChangeRequestReviewCandidate(
                change_request_number=17,
                title="feat: review flow",
                description="summary",
                source_branch="feature/review",
                target_branch="main",
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                head_sha="abc123",
                changes=[],
            )
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_current_user_username",
        _stub_get_current_username("ai-sonar-bot"),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.list_merge_request_notes",
        _stub_list_merge_request_notes(
            [
                MergeRequestNote(
                    id=55,
                    web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
                    author_username="ai-sonar-bot",
                    created_at="2026-05-03T10:00:00Z",
                    body=(
                        "Hi,\n\nHere are your review notes.\n\n"
                        "<!-- ai-sonar-bot:review-note:v1\n"
                        '{"classification":"findings_present","findings":[],"findings_count":0,'
                        '"reviewed_head_sha":"abc123","reviewed_change_request_number":17,'
                        '"schema":"ai-sonar-bot/review-note/v1","summary":"Earlier review."}\n'
                        "-->"
                    ),
                )
            ]
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Earlier classification: findings_present." in summary.message


def test_review_skips_unchanged_sha_when_local_state_is_manual_review_only(
    tmp_path: Path, monkeypatch
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id="123",
        sonarqube_project_key=None,
    )
    state = AppState(repository=RepositoryState(base_branch="main"))
    state.reviews["17:abc123"] = ChangeRequestReviewState(
        change_request_number=17,
        head_sha="abc123",
        status="manual_review_only",
        last_run_id="run-1",
    )
    store.save(state)

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request",
        _stub_get_gitlab_merge_request(
            ChangeRequestReviewCandidate(
                change_request_number=17,
                title="feat: review flow",
                description="summary",
                source_branch="feature/review",
                target_branch="main",
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                head_sha="abc123",
                changes=[],
            )
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Earlier classification: manual_review_only." in summary.message


def test_review_skips_unchanged_sha_when_gitlab_note_is_manual_review_only(
    tmp_path: Path, monkeypatch
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    monkeypatch.setenv("CI_MERGE_REQUEST_IID", "17")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_merge_request",
        _stub_get_gitlab_merge_request(
            ChangeRequestReviewCandidate(
                change_request_number=17,
                title="feat: review flow",
                description="summary",
                source_branch="feature/review",
                target_branch="main",
                web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
                head_sha="abc123",
                changes=[],
            )
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_current_user_username",
        _stub_get_current_username("ai-sonar-bot"),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.list_merge_request_notes",
        _stub_list_merge_request_notes(
            [
                MergeRequestNote(
                    id=55,
                    web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
                    author_username="ai-sonar-bot",
                    created_at="2026-05-03T10:00:00Z",
                    body=(
                        "Hi,\n\nHere are your review notes.\n\n"
                        "<!-- ai-sonar-bot:review-note:v1\n"
                        '{"classification":"manual_review_only","findings":[],"findings_count":0,'
                        '"reviewed_head_sha":"abc123","reviewed_change_request_number":17,'
                        '"schema":"ai-sonar-bot/review-note/v1","summary":"Earlier review."}\n'
                        "-->"
                    ),
                )
            ]
        ),
    )
    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Earlier classification: manual_review_only." in summary.message


def test_review_does_not_reuse_gitlab_same_sha_note_when_bot_username_is_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITLAB_URL", "https://gitlab.example.com")
    monkeypatch.setenv("GITLAB_TOKEN", "token")
    monkeypatch.setenv("GITLAB_PROJECT_ID", "123")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "service.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "gitlab": {
            "target_branch": "main",
            "labels": []
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    merge_request = ChangeRequestReviewCandidate(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=[],
    )
    review_context = ChangeRequestReviewContext(
        change_request_number=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
                start_line=1,
                end_line=1,
                content="   1: value = 1",
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    monkeypatch.setattr(
        "zeroone_ops.services.review.intake.change_request_intake.ChangeRequestIntakeService.select_change_request",
        _stub_select_change_request(merge_request),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.get_current_user_username",
        _stub_raise_runtime_error("cannot resolve bot username"),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.gitlab.GitLabReviewClient.list_merge_request_notes",
        _stub_list_merge_request_notes(
            [
                MergeRequestNote(
                    id=55,
                    web_url="https://gitlab.example.com/group/project/-/merge_requests/17#note_55",
                    author_username="someone-else",
                    created_at="2026-05-03T10:00:00Z",
                    body=(
                        "Hi,\n\nHere are your review notes.\n\n"
                        "<!-- ai-sonar-bot:review-note:v1\n"
                        '{"classification":"findings_present","findings":[],"findings_count":0,'
                        '"reviewed_head_sha":"abc123","reviewed_change_request_number":17,'
                        '"schema":"ai-sonar-bot/review-note/v1","summary":"Earlier review."}\n'
                        "-->"
                    ),
                )
            ]
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(review_context),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        _stub_candidate_stage(
            candidate_result=None,
            raw_review_result=ReviewResult(
                classification="no_findings",
                summary="No findings.",
                findings=[],
            ),
            message="Candidate review generated 0 candidates and accepted 0 findings.",
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." not in summary.message
    assert "Dry-run skipped note publication." in summary.message


def test_review_github_reuses_same_sha_note_when_username_lookup_is_unresolved(
    tmp_path: Path, monkeypatch
) -> None:
    _install_review_precision_fake(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    event_path = tmp_path / "github-event.json"
    event_path.write_text(
        '{"pull_request": {"number": 23, "head": {"sha": "abc123"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "review": {
            "platform": "github"
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "zeroone_ops.providers.review.github.GitHubReviewClient.get_change_request",
        _stub_get_change_request(
            ChangeRequestReviewCandidate(
                change_request_number=23,
                title="feat: github review flow",
                description="summary",
                source_branch="feature/github-review",
                target_branch="main",
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                head_sha="abc123",
                changes=[],
            )
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.github.GitHubReviewClient.get_current_user_username",
        _stub_raise_runtime_error("cannot resolve bot username"),
    )
    monkeypatch.setattr(
        "zeroone_ops.providers.review.github.GitHubReviewClient.list_change_request_comments",
        _stub_list_comments(
            [
                ReviewComment(
                    id=55,
                    web_url="https://github.com/octo-org/octo-repo/pull/23#issuecomment-55",
                    author_username="someone-else",
                    created_at="2026-05-03T10:00:00Z",
                    body=(
                        "Hi,\n\nHere are your review notes.\n\n"
                        "<!-- ai-sonar-bot:review-note:v1\n"
                        '{"classification":"findings_present","findings":[],"findings_count":0,'
                        '"reviewed_head_sha":"abc123","reviewed_change_request_number":23,'
                        '"schema":"ai-sonar-bot/review-note/v1","summary":"Earlier review."}\n'
                        "-->"
                    ),
                )
            ]
        ),
    )

    summary = review(dry_run=True)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Earlier classification: findings_present." in summary.message


def test_review_same_sha_live_run_repairs_pending_projection_without_reanalysis(
    tmp_path: Path, monkeypatch
) -> None:
    class FakeProjectionService:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def project_review(self, **kwargs: object) -> _ProjectionResult:
            self.calls.append(kwargs)
            return _ProjectionResult(action="updated")

    projection_service = FakeProjectionService()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ZEROONE_OPS_CONFIG", str(tmp_path / ".zeroone-ops.json"))
    monkeypatch.setenv("GITHUB_TOKEN", "github-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "octo-org/octo-repo")
    event_path = tmp_path / "github-event.json"
    event_path.write_text(
        '{"pull_request": {"number": 23, "head": {"sha": "abc123"}}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    (tmp_path / ".zeroone-ops.json").write_text(
        """
        {
          "base_branch": "main",
          "execution_mode": "ci",
          "validation_commands": [],
          "review": {
            "platform": "github"
          }
        }
        """.strip(),
        encoding="utf-8",
    )
    state_store = StateStore(
        tmp_path / ".zeroone-ops-state.json",
        base_branch="main",
        gitlab_project_id=None,
        sonarqube_project_key=None,
    )
    state = AppState(repository=RepositoryState(base_branch="main"))
    state.reviews["23:abc123"] = ChangeRequestReviewState(
        change_request_number=23,
        head_sha="abc123",
        status="findings_present",
        last_run_id="prior-run",
        findings_count=1,
        summary="One finding.",
        note_id=1,
        note_url="https://github.com/octo-org/octo-repo/pull/23#issuecomment-1",
        projection_retry_pending=True,
        projection_retry_warning="Review projection warning: transient failure",
    )
    state_store.save(state)

    monkeypatch.setattr(
        "zeroone_ops.providers.review.github.GitHubReviewClient.get_change_request",
        _stub_get_change_request(
            ChangeRequestReviewCandidate(
                change_request_number=23,
                title="feat: github review flow",
                description="summary",
                source_branch="feature/github-review",
                target_branch="main",
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                head_sha="abc123",
                changes=[],
            )
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.context.review_context_builder.ReviewContextBuilder.build",
        _stub_build_context(
            ChangeRequestReviewContext(
                change_request_number=23,
                title="feat: github review flow",
                description="summary",
                source_branch="feature/github-review",
                target_branch="main",
                web_url="https://github.com/octo-org/octo-repo/pull/23",
                head_sha="abc123",
                remediation_context=RemediationReviewContext(
                    source="SonarQube",
                    item_reference="AX123",
                ),
                changed_files=[],
            )
        ),
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_runner.ReviewRunner._build_review_projection_service",
        lambda self: projection_service,
    )
    monkeypatch.setattr(
        "zeroone_ops.services.review.pipeline.review_candidate_generation_service.ReviewCandidateGenerationService.analyze",
        lambda self, context: (_ for _ in ()).throw(AssertionError("analysis should not run")),
    )

    summary = review(dry_run=False)

    assert summary.status.value == "reviewed"
    assert "No new changes after the last review." in summary.message
    assert "Repaired pending review projection." in summary.message
    assert len(projection_service.calls) == 1
    loaded = state_store.load().reviews["23:abc123"]
    assert loaded.projection_retry_pending is False
    assert loaded.projection_retry_warning is None
    assert loaded.last_run_id != "prior-run"
