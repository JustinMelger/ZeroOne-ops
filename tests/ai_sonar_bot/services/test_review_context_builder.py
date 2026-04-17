from pathlib import Path

from ai_sonar_bot.models.config import (
    AnalysisConfig,
    AppConfig,
    ApprovalConfig,
    GitLabConfig,
    ReviewConfig,
)
from ai_sonar_bot.models.review import (
    MergeRequestChangedFile,
    MergeRequestReviewCandidate,
    ReviewFileContext,
    ReviewHelperContext,
)
from ai_sonar_bot.services.review_context_builder import ReviewContextBuilder


def build_config(
    *,
    max_changed_files: int = 10,
    supported_paths: list[str] | None = None,
    ignored_paths: list[str] | None = None,
    enable_helper_following: bool = True,
    max_followed_helpers_per_function: int = 3,
    max_followed_helper_lines: int = 120,
    max_followed_helper_lines_per_review: int = 240,
) -> AppConfig:
    return AppConfig(
        base_branch="main",
        supported_severities=["LOW"],
        supported_issue_types=["CODE_SMELL"],
        validation_commands=[],
        analysis=AnalysisConfig(),
        approval=ApprovalConfig(),
        review=ReviewConfig(
            max_changed_files=max_changed_files,
            max_context_lines_before=1,
            max_context_lines_after=1,
            enable_helper_following=enable_helper_following,
            max_followed_helpers_per_function=max_followed_helpers_per_function,
            max_followed_helper_lines=max_followed_helper_lines,
            max_followed_helper_lines_per_review=max_followed_helper_lines_per_review,
            supported_paths=supported_paths or [],
            ignored_paths=ignored_paths or [],
        ),
        gitlab=GitLabConfig(target_branch="main"),
    )


def build_merge_request(*, changes: list[MergeRequestChangedFile]) -> MergeRequestReviewCandidate:
    return MergeRequestReviewCandidate(
        iid=17,
        title="feat: review flow",
        description="summary",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        changes=changes,
    )


class FakeGitLabReviewClient:
    def __init__(self, detailed_merge_request: MergeRequestReviewCandidate) -> None:
        self.detailed_merge_request = detailed_merge_request

    def get_merge_request(
        self,
        *,
        project_id: str,
        merge_request_iid: int,
    ) -> MergeRequestReviewCandidate:
        del project_id, merge_request_iid
        return self.detailed_merge_request


def test_build_returns_changed_file_context(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text(
        "line1\nline2\nline3\nline4\nline5\n",
        encoding="utf-8",
    )
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -3,1 +3,1 @@\n-line3\n+line3_changed\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.message == ""
    assert result.context.changed_files[0].file_path == "src/service.py"
    assert result.context.changed_files[0].start_line == 2
    assert result.context.changed_files[0].end_line == 4
    assert "   3: line3" in result.context.changed_files[0].content


def test_build_rejects_when_changed_files_exceed_v1_limit(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "a.py").write_text("a = 1\n", encoding="utf-8")
    (source_dir / "b.py").write_text("b = 2\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/a.py",
                new_path="src/a.py",
                diff="@@ -1,1 +1,1 @@",
            ),
            MergeRequestChangedFile(
                old_path="src/b.py",
                new_path="src/b.py",
                diff="@@ -1,1 +1,1 @@",
            ),
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(max_changed_files=1),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is None
    assert "exceeds the v1 limit of 1" in result.message


def test_build_rejects_missing_local_file(tmp_path: Path) -> None:
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/missing.py",
                new_path="src/missing.py",
                diff="@@ -1,1 +1,1 @@",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is None
    assert "Changed file is missing" in result.message


def test_build_filters_to_supported_paths(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text("line1\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="docs/readme.md",
                new_path="docs/readme.md",
                diff="@@ -1,1 +1,1 @@",
            ),
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
            ),
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(supported_paths=["src/"]),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert len(result.context.changed_files) == 1
    assert result.context.changed_files[0].file_path == "src/service.py"


def test_build_filters_ignored_paths_even_when_supported(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir(parents=True)
    generated_dir = source_dir / "generated"
    generated_dir.mkdir()
    (generated_dir / "service.py").write_text("line1\n", encoding="utf-8")
    (source_dir / "service.py").write_text("line1\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/generated/service.py",
                new_path="src/generated/service.py",
                diff="@@ -1,1 +1,1 @@",
            ),
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@",
            ),
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(
            supported_paths=["src/"],
            ignored_paths=["src/generated/"],
        ),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert len(result.context.changed_files) == 1
    assert result.context.changed_files[0].file_path == "src/service.py"


def test_build_parses_remediation_authored_merge_request_context(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text("value = 2\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
            )
        ]
    )
    merge_request.description = "\n".join(
        [
            "## Summary",
            "Update the service guard to avoid a null dereference.",
            "",
            "## Remediation Target",
            "- Source: `SonarQube`",
            "- Issue key: `AX123`",
            "- Rule: `python:S2259`",
            "- Severity: `MAJOR`",
            "- Type: `BUG`",
            "- File: `src/service.py`",
            "- Line: `12`",
            "- Message: Guard against nullable access.",
            "",
            "## Validation",
            "- All validation commands passed.",
            "",
            "## Notes",
            "- Diff was rendered by the bot from a structured edit proposal.",
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.context.remediation_context is not None
    assert result.context.remediation_context.summary == (
        "Update the service guard to avoid a null dereference."
    )
    assert result.context.remediation_context.source == "SonarQube"
    assert result.context.remediation_context.item_reference_label == "Issue key"
    assert result.context.remediation_context.item_reference == "AX123"
    assert result.context.remediation_context.rule_id == "python:S2259"
    assert result.context.remediation_context.severity == "MAJOR"
    assert result.context.remediation_context.remediation_type == "BUG"
    assert result.context.remediation_context.file_path == "src/service.py"
    assert result.context.remediation_context.line == 12
    assert result.context.remediation_context.validation_summary == (
        "All validation commands passed."
    )


def test_build_keeps_working_for_normal_merge_requests_without_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text("value = 2\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
            )
        ]
    )
    merge_request.description = "Human-authored merge request without bot metadata."

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.context.remediation_context is None


def test_build_does_not_set_prior_review_context_by_default(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text("value = 2\n", encoding="utf-8")
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.context.prior_review_context is None


def test_review_file_context_can_carry_supplemental_helper_context() -> None:
    context = ReviewFileContext(
        file_path="src/service.py",
        diff="@@ -1,1 +1,1 @@",
        start_line=1,
        end_line=3,
        content="   1: def service():\n   2:     return helper()\n   3:\n",
        full_file_included=False,
        truncated=True,
        helper_context=[
            ReviewHelperContext(
                file_path="src/service.py",
                symbol="helper",
                start_line=5,
                end_line=6,
                content="   5: def helper():\n   6:     return 1\n",
            )
        ],
    )

    assert context.helper_context[0].symbol == "helper"
    assert context.helper_context[0].file_path == "src/service.py"


def test_build_loads_bounded_repository_guidance(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (source_dir / "service.py").write_text("value = 2\n", encoding="utf-8")
    (tmp_path / "AGENT.md").write_text(
        "\n".join(
            [
                "# Agent Guide",
                "",
                "Use this repository guidance for reviews.",
                "",
                "- Prefer regression tests for behavior changes.",
                "- Keep services narrowly scoped.",
            ]
        ),
        encoding="utf-8",
    )
    (docs_dir / "technical-design-pr-review.md").write_text(
        "\n".join(
            [
                "# Technical Design",
                "",
                "Review notes should stay evidence-backed.",
                "",
                "## Standards",
                "- Prefer no findings over speculative comments.",
            ]
        ),
        encoding="utf-8",
    )
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -1,1 +1,1 @@\n-value = 1\n+value = 2\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert [guidance.file_path for guidance in result.context.repository_guidance] == [
        "AGENT.md",
        "docs/technical-design-pr-review.md",
    ]
    assert "Prefer regression tests" in result.context.repository_guidance[0].summary
    assert "Prefer no findings" in result.context.repository_guidance[1].summary


def test_build_includes_same_file_direct_helper_context_for_python_changes(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text(
        "\n".join(
            [
                "def helper():",
                "    return 1",
                "",
                "def service():",
                "    return helper()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -4,1 +4,1 @@\n-    return 0\n+    return helper()\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    helper_context = result.context.changed_files[0].helper_context
    assert len(helper_context) == 1
    assert helper_context[0].symbol == "helper"
    assert "def helper" in helper_context[0].content


def test_build_skips_helper_context_when_disabled(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text(
        "\n".join(
            [
                "def helper():",
                "    return 1",
                "",
                "def service():",
                "    return helper()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -4,1 +4,1 @@\n-    return 0\n+    return helper()\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(enable_helper_following=False),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.context.changed_files[0].helper_context == []


def test_build_limits_same_file_helper_context_by_budget(tmp_path: Path) -> None:
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    (source_dir / "service.py").write_text(
        "\n".join(
            [
                "def helper():",
                "    value = 1",
                "    return value",
                "",
                "def service():",
                "    return helper()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    merge_request = build_merge_request(
        changes=[
            MergeRequestChangedFile(
                old_path="src/service.py",
                new_path="src/service.py",
                diff="@@ -5,1 +5,1 @@\n-    return 0\n+    return helper()\n",
            )
        ]
    )

    result = ReviewContextBuilder(
        repo_root=tmp_path,
        config=build_config(max_followed_helper_lines=2),
        review_client=FakeGitLabReviewClient(merge_request),
    ).build(merge_request, project_id="123")

    assert result.context is not None
    assert result.context.changed_files[0].helper_context == []
