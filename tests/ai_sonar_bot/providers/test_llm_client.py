from pathlib import Path

from ai_sonar_bot.models.analysis import (
    CodeContextSnippet,
    IssueContext,
    PriorReviewFeedback,
)
from ai_sonar_bot.models.remediation import RemediationExecutionTarget
from ai_sonar_bot.models.review import (
    MergeRequestReviewContext,
    OverlapCandidate,
    OverlapPacket,
    OverlapReconciliationResult,
    PriorReviewContext,
    PriorReviewFinding,
    PriorReviewPass,
    RemediationReviewContext,
    RepositoryGuidanceContext,
    ReviewFileContext,
    ReviewFinding,
    ReviewHelperContext,
    ReviewResult,
)
from ai_sonar_bot.providers.llm_client import FixtureLLMClient
from ai_sonar_bot.providers.llm_fixtures import (
    load_analysis_fixture,
    load_review_fixture,
    load_review_overlap_fixture,
    load_structured_edit_fixture,
)
from ai_sonar_bot.providers.llm_prompts import (
    LLMPromptError,
    build_analysis_prompt,
    build_review_overlap_prompt,
    build_review_prompt,
    build_structured_edit_prompt,
    load_prompt_template,
    render_prompt_template,
)


def test_load_analysis_fixture_returns_issue_analysis(tmp_path: Path) -> None:
    fixture_path = tmp_path / "analysis.json"
    fixture_path.write_text(
        """
        {
          "issue_key": "AX1",
          "classification": "auto_fixable",
          "summary": "Summary",
          "risk_notes": ["risk"],
          "target_files": ["src/service.py"],
          "proposed_strategy": "Do the small safe change."
        }
        """.strip(),
        encoding="utf-8",
    )

    analysis = load_analysis_fixture(fixture_path)

    assert analysis.issue_key == "AX1"
    assert analysis.classification.value == "auto_fixable"
    assert analysis.target_files == ["src/service.py"]


def test_load_structured_edit_fixture_returns_proposal(tmp_path: Path) -> None:
    fixture_path = tmp_path / "edit.json"
    fixture_path.write_text(
        """
        {
          "issue_key": "AX1",
          "edits": [
            {
              "file_path": "src/service.py",
              "search_text": "value = 1",
              "replace_text": "value = 2",
              "line_hint": 1
            }
          ],
          "commit_message": "fix(sonar): update service [AX1]",
          "mr_title": "fix: update service",
          "mr_description": "summary"
        }
        """.strip(),
        encoding="utf-8",
    )

    proposal = load_structured_edit_fixture(fixture_path)

    assert proposal.issue_key == "AX1"
    assert proposal.edits[0].file_path == "src/service.py"
    assert proposal.mr_title == "fix: update service"


def test_load_review_overlap_fixture_returns_overlap_result(tmp_path: Path) -> None:
    fixture_path = tmp_path / "review-overlap.json"
    fixture_path.write_text(
        "\n".join(
            [
                "{",
                '  "prior_reviewed_head_sha": "abc123",',
                '  "resolutions": [',
                "    {",
                '      "outcome": "still_unresolved",',
                '      "current_finding_index": 0,',
                '      "prior_finding_index": 1,',
                '      "related_prior_finding_indices": [1]',
                "    }",
                "  ]",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    result = load_review_overlap_fixture(fixture_path)

    assert isinstance(result, OverlapReconciliationResult)
    assert result.prior_reviewed_head_sha == "abc123"
    assert result.resolutions[0].outcome == "still_unresolved"
    assert result.resolutions[0].prior_finding_index == 1


def test_load_review_fixture_returns_review_result(tmp_path: Path) -> None:
    fixture_path = tmp_path / "review.json"
    fixture_path.write_text(
        "\n".join(
            [
                "{",
                '  "classification": "findings_present",',
                '  "summary": "One medium-risk finding.",',
                '  "review_confidence": 0.83,',
                '  "review_confidence_reason": "The finding is grounded in a small diff.",',
                '  "findings": [',
                "    {",
                '      "severity": "medium",',
                '      "file_path": "src/service.py",',
                '      "title": "Missing test coverage",',
                (
                    '      "evidence": "The diff changes `value = 1` to `value = 2` '
                    'without matching test updates.",'
                ),
                ('      "explanation": "The change alters branch behavior without test updates.",'),
                ('      "suggested_follow_up": "Add a regression test for the changed branch."'),
                "    }",
                "  ]",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    review = load_review_fixture(fixture_path)

    assert isinstance(review, ReviewResult)
    assert review.classification == "findings_present"
    assert review.review_confidence == 0.83
    assert review.findings[0].file_path == "src/service.py"
    assert "value = 1" in review.findings[0].evidence


def test_build_analysis_prompt_uses_prompt_template() -> None:
    issue = RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S100 in src/service.py",
        status="OPEN",
        message="Rename this function.",
        file_path="src/service.py",
        rule_id="python:S100",
        severity="MAJOR",
        issue_type="CODE_SMELL",
        component="project:src/service.py",
        project="project",
        constraints="Keep the fix local to this function.",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=True,
    )

    prompt = build_analysis_prompt(issue, context)

    assert "Issue key: AX1" in prompt
    assert "Constraints: Keep the fix local to this function." in prompt
    assert "This workflow only supports low-risk single-file fixes." in prompt
    assert "Code snippet:\ndef bad_name():\n    return 1\n" in prompt


def test_build_analysis_prompt_includes_prior_review_feedback_when_present() -> None:
    issue = RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S100 in src/service.py",
        status="OPEN",
        message="Rename this function.",
        file_path="src/service.py",
        rule_id="python:S100",
        severity="MAJOR",
        issue_type="CODE_SMELL",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=True,
        prior_review_feedback=PriorReviewFeedback(
            review_status="findings_present",
            review_findings_count=1,
            review_feedback_summary="Previous MR changed ordering semantics.",
            review_confidence=0.81,
            review_confidence_reason="Grounded in the reviewed diff.",
            reviewed_head_sha="abc123",
            retry_count=1,
        ),
    )

    prompt = build_analysis_prompt(issue, context)

    assert "Prior review feedback:" in prompt
    assert "Review status: findings_present" in prompt
    assert "Feedback summary: Previous MR changed ordering semantics." in prompt
    assert "Retry count already consumed: 1" in prompt


def test_build_structured_edit_prompt_uses_prompt_template() -> None:
    issue = RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S100 in src/service.py",
        status="OPEN",
        message="Rename this function.",
        file_path="src/service.py",
        rule_id="python:S100",
        severity="MAJOR",
        issue_type="CODE_SMELL",
        component="project:src/service.py",
        project="project",
        constraints="Keep the fix local to this function.",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=False,
    )

    prompt = build_structured_edit_prompt(issue, context)

    assert "Generate a minimal exact text edit" in prompt
    assert "Constraints: Keep the fix local to this function." in prompt
    assert "Return exactly one edit for one repository-relative file." in prompt
    assert "File path: src/service.py" in prompt


def test_build_structured_edit_prompt_includes_prior_review_feedback_when_present() -> None:
    issue = RemediationExecutionTarget(
        item_id="AX1",
        source_type="sonarqube",
        source_ref="AX1",
        title="python:S100 in src/service.py",
        status="OPEN",
        message="Rename this function.",
        file_path="src/service.py",
        rule_id="python:S100",
        severity="MAJOR",
        issue_type="CODE_SMELL",
    )
    context = IssueContext(
        issue_key="AX1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def bad_name():\n    return 1\n",
        ),
        full_file_included=False,
        truncated=False,
        prior_review_feedback=PriorReviewFeedback(
            review_status="findings_present",
            review_feedback_summary="Previous MR changed ordering semantics.",
        ),
    )

    prompt = build_structured_edit_prompt(issue, context)

    assert "Prior review feedback:" in prompt
    assert "Review status: findings_present" in prompt
    assert "Feedback summary: Previous MR changed ordering semantics." in prompt


def test_build_analysis_prompt_uses_generic_profile_for_unknown_source() -> None:
    issue = RemediationExecutionTarget(
        item_id="pipeline:1",
        source_type="pipeline_failure",
        source_ref="job-1",
        title="pytest failed in src/service.py",
        status="open",
        message="Test suite is failing.",
        file_path="src/service.py",
        severity="HIGH",
    )
    context = IssueContext(
        issue_key="job-1",
        file_path="src/service.py",
        line=8,
        file_size_bytes=128,
        snippet=CodeContextSnippet(
            start_line=4,
            end_line=12,
            content="def test_it():\n    assert False\n",
        ),
        full_file_included=False,
        truncated=True,
    )

    prompt = build_analysis_prompt(issue, context)

    assert "Analyze the following remediation item" in prompt
    assert "Source: Remediation" in prompt
    assert "Item reference: job-1" in prompt
    assert "Constraints: (none)" in prompt


def test_build_review_prompt_uses_prompt_template() -> None:
    context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: add safety check",
        description="Adds validation.",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        repository_guidance=[
            RepositoryGuidanceContext(
                file_path="AGENT.md",
                summary="# Agent Guide\n- Prefer regression tests for behavior changes.",
            )
        ],
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1 +1 @@\n-value = 1\n+value = 2",
                content="value = 2\n",
                start_line=1,
                end_line=1,
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    prompt = build_review_prompt(context)

    assert "Review the merge request and return structured JSON only." in prompt
    assert "thoughtful senior software engineer" in prompt
    assert "REVIEW FOCUS" in prompt
    assert "deterministic runtime errors" in prompt
    assert "leftover debug code affecting runtime behavior" in prompt
    assert "unintended behavioral changes" in prompt
    assert "scope and impact (localized vs shared logic)" in prompt
    assert "ordering, filtering, grouping, selection, and data transformation" in prompt
    assert "Evidence priority:" in prompt
    assert "changed code and its immediate local context as the primary evidence" in prompt
    assert "supporting helper context to confirm, weaken, or refine conclusions" in prompt
    assert "merge request description as background only" in prompt
    assert "Always report deterministic runtime errors." in prompt
    assert "correctness cannot be inferred from visible code" in prompt
    assert "make the narrowest claim the visible code supports" in prompt
    assert (
        "prefer inconsistency, downstream risk, or `manual_review_only` over confirmed breakage"
        in prompt
    )
    assert "do NOT escalate hypothetical misuse or missing-context uncertainty" in prompt
    assert "only describe a regression or breakage when the visible code proves it" in prompt
    assert "When the visible code suggests a possible issue but does not prove it:" in prompt
    assert "do NOT present the issue as confirmed" in prompt
    assert "explain briefly which missing context prevents confirmation" in prompt
    assert "a narrower risk statement, or `no_findings`" in prompt
    assert "binds a runtime constant, config value, or" in prompt
    assert "alias to one concrete scalar value" in prompt
    assert "evaluate the contract using that visible resolved value" in prompt
    assert "mapping or container as the active runtime contract" in prompt
    assert (
        "if the visible code does not show how a config-derived value resolves at runtime" in prompt
    )
    assert "do NOT assume the runtime shape" in prompt
    assert "explain the missing resolution context" in prompt
    assert "tests consistently use the value like a scalar" in prompt
    assert "back off rather than invent a mapping-shaped runtime bug" in prompt
    assert "When reasoning about value shape or runtime type:" in prompt
    assert "treat explicit type hints as strong evidence" in prompt
    assert "only infer value shape from clear visible assignments, returns," in prompt
    assert "and local control flow in the review context" in prompt
    assert "do NOT assume the shape of values derived through helpers, config loaders" in prompt
    assert "makes an implicit default, fallback, or sentinel-driven path" in prompt
    assert "explicit:" in prompt
    assert "clarification or contract hardening rather than breakage" in prompt
    assert "dead fallback logic, unreachable cleanup, or redundant" in prompt
    assert "you may describe that as cleanup or dead code" in prompt
    assert "do NOT escalate it into a runtime regression" in prompt
    assert "supported execution path whose behavior is now broken or materially changed" in prompt
    assert "unknown remaining callers may crash unless a visible unchanged caller" in prompt
    assert "compatibility concern for unseen external consumers" in prompt
    assert "Treat visible request/schema validation as authoritative" in prompt
    assert "Do NOT raise findings based on `None`, missing, or invalid-input paths" in prompt
    assert "schemas that extend a visible base class" in prompt
    assert "treat inherited fields as part of the active contract" in prompt
    assert "field was removed unless" in prompt
    assert "redundant guards or misleading dead checks" in prompt
    assert "degrades gracefully, falls back, or skips optional behavior" in prompt
    assert "distinguish that from a hard end-to-end failure" in prompt
    assert "preserve a usable fallback result" in prompt
    assert "visible code does not support treating them as behavior-preserving" in prompt
    assert "response shape, payload location, or return wiring" in prompt
    assert "distinguish between an inconsistent contract and a confirmed breakage" in prompt
    assert "one visible consumer is compatible" in prompt
    assert "do NOT infer issues from the call site alone" in prompt
    assert "review `prior_review_context`" in prompt
    assert "identify which prior findings are still present" in prompt
    assert "which now appear resolved" in prompt
    assert "which concerns are new in this pass" in prompt
    assert "Do NOT repeat prior findings as if they were brand-new discoveries" in prompt
    assert "Each finding must:" in prompt
    assert "include concrete evidence from the diff or inspected code" in prompt
    assert "reference specific changed behavior" in prompt
    assert "use only the shortest explanation needed to justify the finding" in prompt
    assert (
        "do NOT repeat the same fact across summary, evidence, explanation, and follow-up" in prompt
    )
    assert "SUMMARY" in prompt
    assert "1. What changed" in prompt
    assert "2. Overall assessment" in prompt
    assert "3. Risk level" in prompt
    assert "4. Key reasoning" in prompt
    assert "CLASSIFICATION" in prompt
    assert "Do NOT convert uncertainty into findings." in prompt
    assert "do NOT describe still-open concerns, hidden issues, or unresolved risks" in prompt
    assert "visible code does not justify an actionable finding" in prompt
    assert "if a concern is strong enough to describe as a real unresolved issue" in prompt
    assert "CONFIDENCE" in prompt
    assert "review_confidence_reason" in prompt
    assert "intent is unclear" in prompt
    assert "FINAL DISCIPLINE" in prompt
    assert "Prefer `manual_review_only` when judgment is unreliable" in prompt
    assert "Limit findings to the most important issues (<=5)" in prompt
    assert "Keep findings concise and avoid restating the same point" in prompt
    assert "CONTEXT" in prompt
    assert "Merge request IID: 17" in prompt
    assert "<<BEGIN UNTRUSTED Merge request description>>" in prompt
    assert "Repository guidance:" in prompt
    assert "<<BEGIN REPOSITORY GUIDANCE AGENT.md>>" in prompt
    assert "Remediation-authored context:\n(none)" in prompt
    assert "<<BEGIN UNTRUSTED Changed file: src/service.py>>" in prompt


def test_build_review_prompt_includes_preloaded_input_context_guardrail() -> None:
    context = MergeRequestReviewContext(
        mr_iid=370,
        title="refactor: preload vehicle menu ids",
        description="Reuse precomputed menu ids through manufacturer-order helpers.",
        source_branch="feature/preloaded-ids",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/370",
        head_sha="fe019f12",
        changed_files=[
            ReviewFileContext(
                file_path="core/functions/vehicle_articles_functions.py",
                diff=(
                    "@@ -1,3 +1,6 @@\n"
                    "-unique_ids = await get_all_unique_ids_vehicle_menu(customer_id, erp_system)\n"
                    "+unique_ids = unique_ids_vehicle_menu\n"
                    "+if unique_ids is None:\n"
                    "+    unique_ids = await get_all_unique_ids_vehicle_menu("
                    "customer_id, erp_system)\n"
                ),
                content="unique_ids = unique_ids_vehicle_menu\n",
                start_line=1,
                end_line=4,
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    prompt = build_review_prompt(context)

    assert "preloaded or precomputed inputs" in prompt
    assert "do NOT report a context-mismatch finding unless the visible code shows" in prompt
    assert "same request context" in prompt
    assert "generic misuse scenario" in prompt


def test_build_review_prompt_renders_supporting_helper_context() -> None:
    context = MergeRequestReviewContext(
        mr_iid=18,
        title="refactor: use helper",
        description="Adds helper usage.",
        source_branch="feature/helper",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/18",
        head_sha="def456",
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1 +1 @@\n-return 1\n+return helper()\n",
                content="   1: def service():\n   2:     return helper()\n",
                start_line=1,
                end_line=2,
                full_file_included=False,
                truncated=True,
                helper_context=[
                    ReviewHelperContext(
                        file_path="src/service.py",
                        symbol="helper",
                        start_line=4,
                        end_line=5,
                        content="   4: def helper():\n   5:     return 1\n",
                    )
                ],
            )
        ],
    )

    prompt = build_review_prompt(context)

    assert "Supporting helper context:" in prompt
    assert "<<BEGIN UNTRUSTED Supporting helper: helper>>" in prompt
    assert "File: src/service.py" in prompt
    assert "Lines: 4-5" in prompt
    assert "def helper" in prompt


def test_build_review_prompt_includes_remediation_context_when_present() -> None:
    context = MergeRequestReviewContext(
        mr_iid=17,
        title="fix: add null guard",
        description="Bot-authored remediation merge request.",
        source_branch="ai-sonar/AX123",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="abc123",
        remediation_context=RemediationReviewContext(
            summary="Add a null guard before dereferencing the service result.",
            source="SonarQube",
            item_reference_label="Issue key",
            item_reference="AX123",
            rule_id="python:S2259",
            severity="MAJOR",
            remediation_type="BUG",
            file_path="src/service.py",
            line=12,
            message="Guard against nullable access.",
            validation_summary="All validation commands passed.",
            notes="Diff was rendered by the bot from a structured edit proposal.",
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1 +1 @@\n-value = 1\n+value = 2",
                content="value = 2\n",
                start_line=1,
                end_line=1,
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    prompt = build_review_prompt(context)

    assert "Remediation-authored context:" in prompt
    assert "Summary: Add a null guard before dereferencing the service result." in prompt
    assert "Issue key: AX123" in prompt
    assert "Validation: All validation commands passed." in prompt


def test_build_review_prompt_includes_prior_review_context_when_present() -> None:
    context = MergeRequestReviewContext(
        mr_iid=17,
        title="feat: add safety check",
        description="Adds validation.",
        source_branch="feature/review",
        target_branch="main",
        web_url="https://gitlab.example.com/group/project/-/merge_requests/17",
        head_sha="def456",
        prior_review_context=PriorReviewContext(
            merge_request_iid=17,
            passes=[
                PriorReviewPass(
                    reviewed_head_sha="abc123",
                    classification="findings_present",
                    findings_count=1,
                    summary="One earlier concern still needs attention.",
                    note_url="https://gitlab.example.com/note/55",
                    findings=[
                        PriorReviewFinding(
                            summary="src/service.py: Ordering regression",
                            severity="medium",
                            symbol="Service.run",
                            issue_kind="ordering_regression",
                            region_hint="return-order",
                        )
                    ],
                )
            ],
        ),
        changed_files=[
            ReviewFileContext(
                file_path="src/service.py",
                diff="@@ -1 +1 @@\n-value = 1\n+value = 2",
                content="value = 2\n",
                start_line=1,
                end_line=1,
                full_file_included=True,
                truncated=False,
            )
        ],
    )

    prompt = build_review_prompt(context)

    assert "Prior review context:" in prompt
    assert "<<BEGIN UNTRUSTED Prior review pass 1>>" in prompt
    assert "Reviewed SHA: abc123" in prompt
    assert "Classification: findings_present" in prompt
    assert "Findings count: 1" in prompt
    assert "Summary: One earlier concern still needs attention." in prompt
    assert "- src/service.py: Ordering regression (medium)" in prompt
    assert (
        "[symbol=Service.run, issue_kind=ordering_regression, region_hint=return-order]" in prompt
    )


def test_load_prompt_template_rejects_unknown_template_name() -> None:
    try:
        load_prompt_template("../../../etc/passwd")
    except LLMPromptError as error:
        assert str(error) == "Unsupported prompt template requested: ../../../etc/passwd"
    else:
        raise AssertionError("Expected prompt loader to reject unknown template names.")


def test_render_prompt_template_reports_missing_placeholder(monkeypatch) -> None:
    monkeypatch.setattr(
        "ai_sonar_bot.providers.llm_prompts.load_prompt_template",
        lambda name: "Issue key: {issue_key}\nRule: {rule}\n",
    )

    try:
        render_prompt_template("analyze_issue.txt", issue_key="AX1")
    except LLMPromptError as error:
        assert (
            str(error)
            == "Prompt template could not be rendered because `rule` is missing: analyze_issue.txt"
        )
    else:
        raise AssertionError("Expected prompt rendering to fail on missing placeholders.")


def test_build_review_overlap_prompt_uses_prompt_template() -> None:
    packet = OverlapPacket(
        merge_request_iid=17,
        current_head_sha="def456",
        prior_head_sha="abc123",
        current_findings=[
            ReviewFinding(
                severity="high",
                file_path="src/service.py",
                symbol="Service.run",
                issue_kind="ordering_regression",
                region_hint="return-order",
                title="Ordering logic now returns a different sequence",
                evidence="The diff removes stable ordering.",
                explanation="The returned order can drift between runs.",
                suggested_follow_up="Restore deterministic ordering.",
            )
        ],
        prior_findings=[
            PriorReviewFinding(
                summary="src/service.py: Ordering regression",
                severity="medium",
                symbol="Service.run",
                issue_kind="ordering_regression",
                region_hint="return-order",
            )
        ],
        candidates=[
            OverlapCandidate(
                current_finding_index=0,
                prior_finding_index=0,
                reasons=["same_file", "symbol", "issue_kind"],
            )
        ],
    )

    prompt = build_review_overlap_prompt(packet)

    assert "Compare the current review findings against the latest prior review pass" in prompt
    assert "You are NOT reviewing raw code in this step." in prompt
    assert "Prefer `overlap_ambiguous` over a weak or forced match." in prompt
    assert "Merge request IID: 17" in prompt
    assert "Current reviewed SHA: def456" in prompt
    assert "Prior reviewed SHA: abc123" in prompt
    assert "<<BEGIN UNTRUSTED Current findings>>" in prompt
    assert "current[1] src/service.py: Ordering logic now returns a different sequence" in prompt
    assert "symbol=Service.run" in prompt
    assert "<<BEGIN UNTRUSTED Prior findings>>" in prompt
    assert "prior[1] src/service.py: Ordering regression" in prompt
    assert "<<BEGIN UNTRUSTED Overlap candidates>>" in prompt
    assert "current[1] <-> prior[1] reasons=same_file, symbol, issue_kind" in prompt


def test_fixture_llm_client_loads_review_overlap_result(tmp_path: Path) -> None:
    fixture_path = tmp_path / "review-overlap.json"
    fixture_path.write_text(
        "\n".join(
            [
                "{",
                '  "prior_reviewed_head_sha": "abc123",',
                '  "resolutions": [',
                "    {",
                '      "outcome": "still_unresolved",',
                '      "current_finding_index": 0,',
                '      "prior_finding_index": 0,',
                '      "related_prior_finding_indices": [0]',
                "    }",
                "  ]",
                "}",
            ]
        ),
        encoding="utf-8",
    )
    client = FixtureLLMClient(
        analysis_fixture_path=tmp_path / "analysis.json",
        review_overlap_fixture_path=fixture_path,
    )

    result = client.review_overlap_reconciliation(
        OverlapPacket(
            merge_request_iid=17,
            current_head_sha="def456",
            prior_head_sha="abc123",
            current_findings=[],
            prior_findings=[],
            candidates=[],
        )
    )

    assert result.prior_reviewed_head_sha == "abc123"
    assert result.resolutions[0].outcome == "still_unresolved"
