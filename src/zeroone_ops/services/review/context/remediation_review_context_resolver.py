"""Resolve persisted remediation evidence through a uniquely linked work item."""

import logging
from collections.abc import Callable

import httpx

from zeroone_ops.models.review import ChangeRequestReviewContext, RemediationReviewContext
from zeroone_ops.models.review_linkage import LinkedReviewWorkItem
from zeroone_ops.providers.github_client import GitHubClientError
from zeroone_ops.providers.gitlab_client import GitLabClientError
from zeroone_ops.settings import SettingsError


class RemediationReviewContextResolver:
    """Enrich review context without owning provider lookup or review decisions."""

    def __init__(
        self,
        *,
        lookup: Callable[[str, int], LinkedReviewWorkItem | None],
        logger: logging.Logger,
    ) -> None:
        """Retain lazy lookup and existing warning ownership without performing I/O."""
        self.lookup = lookup
        self.logger = logger

    def resolve(
        self, *, repository_id: str, context: ChangeRequestReviewContext
    ) -> ChangeRequestReviewContext:
        """Attach authoritative evidence only after exact linked-request URL verification."""
        try:
            linked = self.lookup(repository_id, context.change_request_number)
        except (GitHubClientError, GitLabClientError, SettingsError, httpx.HTTPError):
            self.logger.warning("review work-item context lookup failed", exc_info=True)
            return context

        if linked is None:
            return context

        work_item = linked.work_item
        if (
            work_item.linked_change_request is None
            or work_item.linked_change_request.web_url != context.web_url
        ):
            return context

        remediation_context = context.remediation_context or RemediationReviewContext()
        return context.model_copy(
            update={
                "remediation_context": remediation_context.model_copy(
                    update={
                        "verified_work_item_url": linked.issue_url,
                        "batch_attempt": work_item.batch_attempt,
                        "semantic_safety": (
                            None
                            if work_item.semantic_safety is None
                            else work_item.semantic_safety.assessment
                        ),
                    }
                )
            }
        )
