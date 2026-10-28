"""Offline V1 precision cases: behavior evidence and wiring, not model accuracy."""

import ast
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from zeroone_ops.models.config import AppConfig, GitLabConfig, RemediationConfig, ReviewConfig
from zeroone_ops.models.review import (
    ChangeRequestChangedFile,
    ChangeRequestReviewCandidate,
    ChangeRequestReviewContext,
    DroppedCandidate,
    PrecisionAcceptedFinding,
    PrecisionReviewDecision,
    ReviewComment,
    ReviewFinding,
    ReviewHelperContext,
    ReviewResult,
)
from zeroone_ops.providers.llm_prompts import (
    build_candidate_review_prompt,
    build_review_precision_prompt,
)
from zeroone_ops.services.review.context.review_context_builder import ReviewContextBuilder
from zeroone_ops.services.review.continuity.review_prior_comment_parser import (
    ChangeRequestPriorCommentParser,
)
from zeroone_ops.services.review.pipeline.review_artifact_builder import ReviewArtifactBuilder
from zeroone_ops.services.review.pipeline.review_artifact_validator import ReviewArtifactValidator
from zeroone_ops.services.review.pipeline.review_candidate_generation_service import (
    ReviewCandidateGenerationService,
)
from zeroone_ops.services.review.pipeline.review_reconciliation_service import (
    ReviewReconciliationService,
)

FIXTURES = Path(__file__).parent / "fixtures" / "precision_v1"


class PrecisionCase(BaseModel):
    """Load only the test inputs needed by existing review interfaces."""

    name: str
    candidate: ChangeRequestReviewCandidate
    file_path: str
    finding: ReviewFinding
    mock_disposition: Literal["drop", "narrow", "retain"]
    published_identity: str | None = None
    review_note_reference: str | None = None
    source_sha256: dict[str, str] = Field(default_factory=dict)

    def source(self, version: Literal["before", "after"]) -> str:
        """Return one frozen source snapshot without normalization."""
        return (FIXTURES / self.name / f"{version}.txt").read_text(encoding="utf-8")

    def change_request(self) -> ChangeRequestReviewCandidate:
        """Rehydrate the exact diff, preserving space-prefixed context lines."""
        diff_lines = json.loads((FIXTURES / self.name / "change.json").read_text(encoding="utf-8"))
        return self.candidate.model_copy(
            update={
                "changes": [
                    ChangeRequestChangedFile(
                        old_path=self.file_path,
                        new_path=self.file_path,
                        diff="\n".join(diff_lines) + "\n",
                    )
                ]
            },
            deep=True,
        )


CASES = [
    PrecisionCase.model_validate(case)
    for case in json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
]


def build_config() -> AppConfig:
    return AppConfig(
        base_branch="main",
        gitlab=GitLabConfig(),
        remediation=RemediationConfig(target_branch="main"),
        review=ReviewConfig(
            max_changed_files=5,
            max_findings_per_review=3,
            max_prior_review_passes=2,
            inline_comments_enabled=False,
            supported_paths=["src/", "tests/"],
            ignored_paths=[],
        ),
    )


def build_context(case: PrecisionCase, repo_root: Path) -> ChangeRequestReviewContext:
    target = repo_root / case.file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(case.source("after"), encoding="utf-8")
    if case.name != "annotation":
        (repo_root / "AGENTS.md").write_text(
            (FIXTURES / "guidance.txt").read_text(encoding="utf-8"), encoding="utf-8"
        )
    result = ReviewContextBuilder(repo_root=repo_root, config=build_config()).build(
        case.change_request()
    )
    assert result.context is not None, result.message
    return result.context


def execute_fixture(source: str) -> dict:
    """Execute checked-in synthetic/demo code, never remote code fetched by tests."""
    namespace = {}
    exec(compile(source, "<precision-fixture>", "exec", dont_inherit=True), namespace)
    return namespace


def scripted_precision(case: PrecisionCase) -> PrecisionReviewDecision:
    """Supply explicit test decisions; these are not historical model responses."""
    if case.mock_disposition == "drop":
        return PrecisionReviewDecision(
            review_classification="no_findings",
            decision_summary="No new defect demonstrated by the annotation change.",
            decision_rationale="The boolean-ID behavior is unchanged from the base.",
            dropped_candidates=[
                DroppedCandidate(candidate_id="candidate-1", drop_reason="unsupported_scope")
            ],
        )

    finding = case.finding
    explanation = finding.explanation
    if case.mock_disposition == "narrow":
        explanation = (
            "Direct helper callers passing non-booleans observe a changed field type; "
            "the supplied validated HTTP path does not demonstrate an API regression."
        )
    return PrecisionReviewDecision(
        review_classification="findings_present",
        decision_summary="One bounded concern remains.",
        decision_rationale="The supplied code supports the stated local behavior.",
        accepted_findings=[
            PrecisionAcceptedFinding(
                source_candidate_ids=["candidate-1"],
                severity="low" if case.mock_disposition == "narrow" else finding.severity,
                file_path=finding.file_path,
                line_start=finding.line_start,
                line_end=finding.line_end,
                title=finding.title,
                summary=finding.title,
                evidence=[finding.evidence],
                why_it_matters=explanation,
                recommended_follow_up=finding.suggested_follow_up,
            )
        ],
    )


class ScriptedReviewClient:
    """Record two offline stage calls without creating a network client."""

    def __init__(self, case: PrecisionCase, decision: PrecisionReviewDecision) -> None:
        self.case = case
        self.decision = decision
        self.contexts = []
        self.forwarded = []
        self.precision_prompt = ""

    def review_merge_request(self, context: ChangeRequestReviewContext) -> ReviewResult:
        self.contexts.append(context)
        return ReviewResult(
            classification="findings_present",
            summary="Seeded from public finding evidence, not captured candidate output.",
            findings=[self.case.finding.model_copy(deep=True)],
        )

    def review_precision_reconciliation(self, context, **kwargs) -> PrecisionReviewDecision:
        self.contexts.append(context)
        self.forwarded = kwargs["candidates"]
        self.precision_prompt = build_review_precision_prompt(context, **kwargs)
        return self.decision.model_copy(deep=True)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_frozen_diff_matches_exact_source_snapshots(case: PrecisionCase) -> None:
    for version, expected_digest in case.source_sha256.items():
        assert hashlib.sha256(case.source(version).encode("utf-8")).hexdigest() == expected_digest
    generated = "".join(
        difflib.unified_diff(
            case.source("before").splitlines(keepends=True),
            case.source("after").splitlines(keepends=True),
        )
    ).splitlines()[2:]
    recorded = case.change_request().changes[0].diff.splitlines()
    normalized = [re.sub(r"(@@.*?@@).*", r"\1", line) for line in recorded]
    assert generated == normalized


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.name)
def test_context_and_precision_lineage_reach_artifact_without_reinterpretation(
    case: PrecisionCase, tmp_path: Path
) -> None:
    context = build_context(case, tmp_path)
    original_context = context.model_copy(deep=True)
    assert context.head_sha == case.candidate.head_sha
    assert context.diff_refs == case.candidate.diff_refs
    assert context.prior_review_context is None
    assert [changed.file_path for changed in context.changed_files] == [case.file_path]
    assert context.changed_files[0].diff == case.change_request().changes[0].diff
    if case.name != "annotation":
        assert context.repository_guidance
    if case.name == "mr19":
        # Supplemental caller evidence is a reconstruction, not default discovery.
        for file_name in ("routes", "store", "validation"):
            source = (
                CASES[0].source("before")
                if file_name == "validation"
                else (FIXTURES / "mr19" / f"{file_name}.txt").read_text(encoding="utf-8")
            )
            context.changed_files[0].helper_context.append(
                ReviewHelperContext(
                    file_path=f"src/task_api/{file_name}.py",
                    symbol="reconstructed caller evidence",
                    start_line=1,
                    end_line=len(source.splitlines()),
                    content=source,
                )
            )

    decision = scripted_precision(case)
    client = ScriptedReviewClient(case, decision)
    stage = ReviewCandidateGenerationService(build_config(), lambda: client).analyze(context)
    result = ReviewReconciliationService(build_config(), lambda: client).reconcile(
        context=context, candidate_stage_result=stage
    )
    assert stage.forwarded_candidate_ids == ("candidate-1",)
    assert client.forwarded == stage.candidate_result.findings
    assert len(client.contexts) == 2
    assert all(recorded is context for recorded in client.contexts)
    assert result.reconciled_decision is not None
    assert result.precision_decision == decision
    artifact = (
        ReviewArtifactBuilder()
        .build(reconciled_decision=result.reconciled_decision, overlap_result=result.overlap_result)
        .artifact
    )
    assert ReviewArtifactValidator().validate(artifact).status == "valid"
    assert artifact.classification == decision.review_classification
    assert [finding.title for finding in artifact.findings] == [
        finding.title for finding in decision.accepted_findings
    ]
    assert [finding.explanation for finding in artifact.findings] == [
        finding.why_it_matters for finding in decision.accepted_findings
    ]
    assert all(
        finding.source_candidate_ids == ["candidate-1"]
        for finding in result.reconciled_decision.accepted_findings
    )
    assert "do not drop it only because branch-wide reachability" in client.precision_prompt
    assert case.candidate.head_sha in build_candidate_review_prompt(context)
    assert original_context.changed_files[0].content == context.changed_files[0].content


def test_context_reconstruction_does_not_verify_worktree_identity(tmp_path: Path) -> None:
    case = CASES[0]
    build_context(case, tmp_path)
    (tmp_path / case.file_path).write_text(case.source("before"), encoding="utf-8")
    result = ReviewContextBuilder(tmp_path, build_config()).build(case.change_request())
    assert result.context is not None
    assert result.context.head_sha == case.candidate.head_sha
    assert "def validate_task_ids(body):" in result.context.changed_files[0].content
    assert "def validate_task_ids(body: dict" not in result.context.changed_files[0].content


def test_reconstructed_contexts_remain_isolated_in_a_shared_workspace(tmp_path: Path) -> None:
    presentation = build_context(CASES[1], tmp_path)
    validation = build_context(CASES[0], tmp_path)
    assert presentation.change_request_number == 19
    assert validation.change_request_number == 24
    assert presentation.changed_files[0].file_path == "src/task_api/presentation.py"
    assert validation.changed_files[0].file_path == "src/task_api/validation.py"
    assert "def present_task" not in validation.changed_files[0].content
    assert "def validate_task_ids" not in presentation.changed_files[0].content
    assert presentation.head_sha != validation.head_sha


def test_default_helper_discovery_does_not_supply_reverse_http_callers(tmp_path: Path) -> None:
    case = CASES[1]
    build_context(case, tmp_path)
    source_root = tmp_path / "src" / "task_api"
    for file_name in ("routes", "store"):
        (source_root / f"{file_name}.py").write_text(
            (FIXTURES / "mr19" / f"{file_name}.txt").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    (source_root / "validation.py").write_text(CASES[0].source("before"), encoding="utf-8")
    result = ReviewContextBuilder(tmp_path, build_config()).build(case.change_request())
    assert result.context is not None
    assert result.context.changed_files[0].helper_context == []
    assert "def update_task" not in build_candidate_review_prompt(result.context)


def test_precision_rejects_unknown_candidate_lineage(tmp_path: Path) -> None:
    case = CASES[2]
    decision = scripted_precision(case)
    decision.accepted_findings[0].source_candidate_ids = ["another-mr-candidate"]
    client = ScriptedReviewClient(case, decision)
    context = build_context(case, tmp_path)
    stage = ReviewCandidateGenerationService(build_config(), lambda: client).analyze(context)
    result = ReviewReconciliationService(build_config(), lambda: client).reconcile(
        context=context, candidate_stage_result=stage
    )
    assert result.reconciled_decision is not None
    assert result.reconciled_decision.review_classification == "manual_review_only"
    assert result.reconciled_decision.accepted_findings == []


@pytest.mark.parametrize("case", CASES[:2], ids=lambda case: case.name)
def test_published_note_identity_cannot_be_loaded_for_other_mr(case: PrecisionCase) -> None:
    finding = case.finding.model_dump()
    payload = {
        "schema": "ai-sonar-bot/review-note/v1",
        "reviewed_change_request_number": case.candidate.change_request_number,
        "reviewed_head_sha": case.candidate.head_sha,
        "classification": "findings_present",
        "summary": case.finding.title,
        "findings_count": 1,
        "findings": [
            {**finding, "identity": case.published_identity, "summary": case.finding.title}
        ],
    }
    note = ReviewComment(
        id=int(case.review_note_reference.rsplit("-", 1)[1]),
        body="<!-- ai-sonar-bot:review-note:v1\n" + json.dumps(payload) + "\n-->",
    )
    parser = ChangeRequestPriorCommentParser()
    correct = parser.parse_note(
        note=note, expected_change_request_number=case.candidate.change_request_number
    )
    assert correct.prior_review_pass is not None
    assert correct.prior_review_pass.reviewed_head_sha == case.candidate.head_sha
    assert correct.prior_review_pass.findings[0].identity == case.published_identity
    assert parser.parse_note(note=note, expected_change_request_number=99).prior_review_pass is None


@pytest.mark.parametrize("version", ["before", "after"])
def test_mr24_boolean_acceptance_predates_annotations(version: str) -> None:
    namespace = execute_fixture(CASES[0].source(version))
    assert namespace["validate_task_ids"]({"task_ids": [True, 2]}) == [True, 2]
    with pytest.raises(ValueError, match="positive integers"):
        namespace["validate_task_ids"]({"task_ids": [False]})
    assert issubclass(bool, int)


def test_mr24_function_bodies_are_identical() -> None:
    before = ast.parse(CASES[0].source("before"))
    after = ast.parse(CASES[0].source("after"))
    for old, new in zip(before.body, after.body, strict=True):
        if isinstance(old, ast.FunctionDef):
            assert isinstance(new, ast.FunctionDef)
            assert [ast.dump(node) for node in old.body] == [ast.dump(node) for node in new.body]
        else:
            assert ast.dump(old) == ast.dump(new)


@pytest.mark.parametrize("completed", [False, True])
def test_mr19_validated_store_path_preserves_boolean_responses(completed: bool) -> None:
    validate = execute_fixture(CASES[0].source("before"))["validate_body"]
    store = execute_fixture((FIXTURES / "mr19" / "store.txt").read_text())["TaskStore"]()
    created = store.create("task")
    updated = store.update(created["id"], validate({"completed": completed}, creating=False))
    tasks = [created, updated, store.get(created["id"]), *store.list(None, 0, 20)]
    tasks.extend(store.complete_many([created["id"]]))
    old = execute_fixture(CASES[1].source("before"))["present_task"]
    new = execute_fixture(CASES[1].source("after"))["present_task"]
    for task in tasks:
        assert old(task) == new(task)
        assert type(new(task)["completed"]) is bool
    for invalid in ("true", 1, None):
        with pytest.raises(ValueError, match="boolean"):
            validate({"completed": invalid}, creating=False)


def test_mr19_direct_nonboolean_call_changes_local_contract() -> None:
    task = {"id": 1, "title": "task", "completed": "yes"}
    old = execute_fixture(CASES[1].source("before"))["present_task"]
    new = execute_fixture(CASES[1].source("after"))["present_task"]
    assert old(task)["completed"] is False
    assert new(task)["completed"] == "yes"


@pytest.mark.skipif(
    sys.version_info >= (3, 14), reason="Control targets Python 3.13 eager annotations"
)
def test_annotation_positive_control_fails_at_import_without_calling_function() -> None:
    assert execute_fixture(CASES[2].source("before"))["present"](1) == 1
    with pytest.raises(NameError, match="MissingType"):
        execute_fixture(CASES[2].source("after"))
