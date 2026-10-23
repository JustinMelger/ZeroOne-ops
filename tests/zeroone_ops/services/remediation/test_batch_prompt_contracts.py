"""Keep internal batch contracts separate from production model requests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from openai.lib._pydantic import to_strict_json_schema
from test_analysis_service import build_config
from test_batch_analysis_execution import analysis, batch_target, write_source

from zeroone_ops.models.analysis import BatchIssueAnalysis, IssueAnalysis, StructuredEditProposal
from zeroone_ops.models.batch_execution import BatchAnalysisCoverage
from zeroone_ops.models.config import OpenAIConnectionConfig
from zeroone_ops.models.review import ChangeRequestReviewContext, RemediationReviewContext
from zeroone_ops.providers.llm_client import FixtureLLMClient, OpenAILLMClient
from zeroone_ops.providers.llm_prompts import build_candidate_review_prompt
from zeroone_ops.services.remediation.remediation_context_builder import RemediationContextBuilder


@pytest.mark.parametrize("batched", [False, True])
def test_analysis_and_edit_requests_select_only_their_own_contract(tmp_path, batched):
    write_source(tmp_path)
    target = batch_target()
    if not batched:
        target = target.model_copy(update={"batch": None, "batch_attempt": None})
    context = RemediationContextBuilder(tmp_path, build_config()).build(target)
    response = analysis(BatchAnalysisCoverage(addressable_ids=("member-0", "member-1")))
    client = OpenAILLMClient(
        config=OpenAIConnectionConfig(api_key="test-key", model="test-model"),
        solution_output_path=None,
    )
    parse = Mock(return_value=SimpleNamespace(output_parsed=response))
    client.client = SimpleNamespace(responses=SimpleNamespace(parse=parse))

    client.analyze_issue(target, context)
    request = parse.call_args.kwargs
    expected = BatchIssueAnalysis if batched else IssueAnalysis
    assert request["text_format"] is expected
    schema = to_strict_json_schema(expected)
    assert ("batch_coverage" in schema["required"]) == batched
    assert ("BatchAnalysisCoverage" in schema.get("$defs", {})) == batched
    analysis_prompt = request["input"][1]["content"]
    assert ("must partition" in analysis_prompt) == batched
    assert ("Batch attempt evidence" in analysis_prompt) == batched

    parse.return_value = SimpleNamespace(
        output_parsed=StructuredEditProposal(
            issue_key="test",
            commit_message="test",
            change_request_title="test",
            change_request_description="test",
        )
    )
    client.generate_structured_edit(target, context)
    request = parse.call_args.kwargs
    assert request["text_format"] is StructuredEditProposal
    edit_prompt = request["input"][1]["content"]
    assert ("Batch attempt evidence" in edit_prompt) == batched
    assert "must partition" not in edit_prompt
    if batched:
        assert "Independent local edits" in edit_prompt
    else:
        assert "Use multiple edits only when they are tightly coupled" in edit_prompt
        assert "batch_coverage" not in edit_prompt


@pytest.mark.parametrize("batched", [False, True])
def test_fixture_analysis_uses_same_schema_selection_as_live_requests(tmp_path, batched):
    write_source(tmp_path)
    target = batch_target()
    if not batched:
        target = target.model_copy(update={"batch": None, "batch_attempt": None})
    context = RemediationContextBuilder(tmp_path, build_config()).build(target)
    coverage = BatchAnalysisCoverage(addressable_ids=("member-0", "member-1"))
    fixture = tmp_path / "analysis.json"
    fixture.write_text(analysis(coverage).model_dump_json(), encoding="utf-8")

    result = FixtureLLMClient(fixture).analyze_issue(target, context)

    assert type(result) is (BatchIssueAnalysis if batched else IssueAnalysis)
    if batched:
        assert result.batch_coverage == coverage
    else:
        assert "batch_coverage" not in result.model_dump()


def test_review_batch_prompt_handoff_remains_deferred():
    target = batch_target()
    context = ChangeRequestReviewContext(
        change_request_number=1,
        title="Review",
        source_branch="fix",
        target_branch="main",
        head_sha="head",
        web_url="https://example/requests/1",
        changed_files=[],
        remediation_context=RemediationReviewContext(batch_attempt=target.batch_attempt),
    )
    prompt = build_candidate_review_prompt(context)
    assert "Verified batch attempt" not in prompt
    assert "member-0" not in prompt
    assert "targeted scope and accounting" not in prompt
